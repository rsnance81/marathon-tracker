"""Marathon training tracker — Streamlit + GitHub-backed storage.

Data lives as two CSVs in this same GitHub repo:
  plan.csv:  Week,Start Date,Planned Miles
  runs.csv:  Date,Miles,Note

Secrets (Streamlit Cloud -> App settings -> Secrets):
  [github]
  token = "github_pat_..."          # fine-grained PAT, Contents: read/write on this repo
  repo = "yourusername/marathon-tracker"

  [app]
  race_date = "2027-01-17"
"""

import io
from datetime import date, datetime, timedelta

import altair as alt
import pandas as pd
import streamlit as st
from github import Auth, Github

st.set_page_config(page_title="Marathon Tracker", page_icon="🏃", layout="centered")

PLAN_PATH = "plan.csv"
RUNS_PATH = "runs.csv"


# ---------------------------------------------------------------- data layer
@st.cache_resource
def get_repo():
    gh = Github(auth=Auth.Token(st.secrets["github"]["token"]))
    return gh.get_repo(st.secrets["github"]["repo"])


def _read_csv(path: str) -> tuple[pd.DataFrame, str]:
    """Return (dataframe, blob_sha) for a CSV in the repo."""
    f = get_repo().get_contents(path)
    df = pd.read_csv(io.BytesIO(f.decoded_content))
    return df, f.sha


@st.cache_data(ttl=120)
def load_data() -> tuple[pd.DataFrame, pd.DataFrame]:
    plan, _ = _read_csv(PLAN_PATH)
    plan.columns = [c.strip() for c in plan.columns]
    plan["Start Date"] = pd.to_datetime(plan["Start Date"]).dt.date
    plan["Planned Miles"] = pd.to_numeric(plan["Planned Miles"], errors="coerce").fillna(0)
    plan = plan.sort_values("Start Date").reset_index(drop=True)

    try:
        runs, _ = _read_csv(RUNS_PATH)
    except Exception:  # noqa: BLE001 — file missing on first launch
        runs = pd.DataFrame(columns=["Date", "Miles", "Note"])
    runs.columns = [c.strip() for c in runs.columns]
    if not runs.empty:
        runs["Date"] = pd.to_datetime(runs["Date"]).dt.date
        runs["Miles"] = pd.to_numeric(runs["Miles"], errors="coerce").fillna(0)
        runs["Note"] = runs["Note"].fillna("")
    return plan, runs


def save_runs(runs: pd.DataFrame, message: str) -> None:
    """Write runs.csv back to the repo (create it if it doesn't exist yet)."""
    repo = get_repo()
    out = runs.sort_values("Date").copy()
    out["Date"] = out["Date"].map(lambda d: d.isoformat())
    content = out.to_csv(index=False)
    try:
        existing = repo.get_contents(RUNS_PATH)
        repo.update_file(RUNS_PATH, message, content, existing.sha)
    except Exception:  # noqa: BLE001
        repo.create_file(RUNS_PATH, message, content)
    load_data.clear()


# ------------------------------------------------------------- calculations
def assign_week(run_date: date, plan: pd.DataFrame) -> int | None:
    """Return the plan index (0-based) whose 7-day window contains run_date."""
    for i in range(len(plan) - 1, -1, -1):
        start = plan.loc[i, "Start Date"]
        if run_date >= start:
            in_window = run_date < start + timedelta(days=7)
            return i if (in_window or i == len(plan) - 1) else None
    return None


def build_weekly(plan: pd.DataFrame, runs: pd.DataFrame) -> pd.DataFrame:
    weekly = plan.copy()
    weekly["Actual"] = 0.0
    for _, r in runs.iterrows():
        i = assign_week(r["Date"], plan)
        if i is not None:
            weekly.loc[i, "Actual"] += r["Miles"]
    return weekly


# ------------------------------------------------------------------- layout
try:
    plan, runs = load_data()
except Exception as exc:  # noqa: BLE001
    st.error(
        "Couldn't load data from GitHub. Check that the token has Contents "
        "read/write on the repo, the repo name in secrets is correct, and "
        "plan.csv exists.\n\n"
        f"Details: {exc}"
    )
    st.stop()

if plan.empty:
    st.warning("plan.csv is empty. Add rows: Week,Start Date,Planned Miles.")
    st.stop()

today = date.today()
race_date = datetime.fromisoformat(st.secrets["app"]["race_date"]).date()
weekly = build_weekly(plan, runs)

cur_idx = None
for i, start in enumerate(weekly["Start Date"]):
    if today >= start:
        cur_idx = i

# ---- header
days_left = max(0, (race_date - today).days)
if cur_idx is not None:
    st.title(f"Week {weekly.loc[cur_idx, 'Week']} of {len(weekly)}")
else:
    st.title("Pre-plan")
st.caption(f"🏁 {race_date:%B %d, %Y} · **{days_left} days to race**")

# ---- this-week metrics
if cur_idx is not None:
    wk = weekly.loc[cur_idx]
    remaining = max(0.0, wk["Planned Miles"] - wk["Actual"])
    c1, c2, c3 = st.columns(3)
    c1.metric("This week", f"{wk['Actual']:.1f} mi")
    c2.metric("Plan", f"{wk['Planned Miles']:.0f} mi")
    c3.metric("To go", f"{remaining:.1f} mi")
    if wk["Planned Miles"] > 0:
        st.progress(min(1.0, wk["Actual"] / wk["Planned Miles"]))

    done = weekly.iloc[:cur_idx]
    if len(done):
        delta = done["Actual"].sum() - done["Planned Miles"].sum()
        st.metric(
            "Cumulative vs plan (completed weeks)",
            f"{done['Actual'].sum():.1f} / {done['Planned Miles'].sum():.0f} mi",
            delta=f"{delta:+.1f} mi",
        )

st.divider()

# ---- log a run
st.subheader("Log a run")
with st.form("log_run", clear_on_submit=True):
    f1, f2 = st.columns([1.2, 1])
    run_date = f1.date_input("Date", value=today)
    miles = f2.number_input("Miles", min_value=0.0, step=0.5, format="%.1f")
    note = st.text_input("Note (optional)", placeholder="Easy run, tempo, long run…")
    if st.form_submit_button("Add run", use_container_width=True, type="primary"):
        if miles > 0:
            new = pd.DataFrame([{"Date": run_date, "Miles": miles, "Note": note}])
            save_runs(
                pd.concat([runs, new], ignore_index=True),
                f"Log {miles:.1f} mi on {run_date.isoformat()}",
            )
            st.success(f"Logged {miles:.1f} mi on {run_date:%b %d}.")
            st.rerun()
        else:
            st.warning("Enter a mileage greater than zero.")

st.divider()

# ---- weekly chart
st.subheader("Weekly mileage vs plan")
chart_df = weekly.assign(
    Label=[f"W{w}" for w in weekly["Week"]],
    Actual=[
        a if (cur_idx is not None and i <= cur_idx) else None
        for i, a in enumerate(weekly["Actual"])
    ],
)
base = alt.Chart(chart_df).encode(
    x=alt.X("Label:N", sort=None, title=None, axis=alt.Axis(labelAngle=0))
)
bars = base.mark_bar(color="#1F3BE0", size=14).encode(
    y=alt.Y("Actual:Q", title="miles"),
    tooltip=["Label", alt.Tooltip("Actual:Q", format=".1f"), "Planned Miles"],
)
plan_line = base.mark_line(
    color="#121417", strokeDash=[5, 3], interpolate="step-after", strokeWidth=2
).encode(y="Planned Miles:Q")
st.altair_chart(bars + plan_line, use_container_width=True)

# ---- week table + run management
tab1, tab2 = st.tabs(["Weeks", "Runs"])
with tab1:
    show = weekly.copy()
    show["Start Date"] = show["Start Date"].map(lambda d: f"{d:%b %d}")
    show["Actual"] = [
        f"{a:.1f}" if (cur_idx is not None and i <= cur_idx) else "—"
        for i, a in enumerate(show["Actual"])
    ]
    st.dataframe(
        show[["Week", "Start Date", "Planned Miles", "Actual"]],
        hide_index=True,
        use_container_width=True,
    )
with tab2:
    if runs.empty:
        st.info("No runs logged yet.")
    else:
        recent = runs.sort_values("Date", ascending=False).reset_index(drop=True)
        display = recent.copy()
        display["Date"] = display["Date"].map(lambda d: f"{d:%a %b %d}")
        st.dataframe(display, hide_index=True, use_container_width=True)

        with st.expander("Delete a run"):
            options = [
                f"{r['Date']:%b %d} — {r['Miles']:.1f} mi"
                + (f" ({r['Note']})" if r["Note"] else "")
                for _, r in recent.iterrows()
            ]
            pick = st.selectbox("Select run", options, index=None, placeholder="Choose…")
            if pick is not None and st.button("Delete selected run", type="secondary"):
                idx = options.index(pick)
                target = recent.iloc[idx]
                mask = ~(
                    (runs["Date"] == target["Date"])
                    & (runs["Miles"] == target["Miles"])
                    & (runs["Note"] == target["Note"])
                )
                # drop only the first matching row
                dupes = runs[~mask]
                keep = pd.concat([runs[mask], dupes.iloc[1:]], ignore_index=True)
                save_runs(keep, f"Delete run {target['Date'].isoformat()}")
                st.rerun()

if st.button("↻ Refresh"):
    load_data.clear()
    st.rerun()
