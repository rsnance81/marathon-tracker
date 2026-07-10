"""Marathon training tracker — Streamlit + Google Sheets.

Sheet structure (two tabs):
  Plan: Week | Start Date | Planned Miles
  Runs: Date | Miles | Note

Secrets (Streamlit Cloud -> App settings -> Secrets):
  [gcp_service_account]  (full service-account JSON as TOML)
  [sheet]
  url = "https://docs.google.com/spreadsheets/d/.../edit"
  race_date = "2027-01-17"
"""

from datetime import date, datetime, timedelta

import altair as alt
import gspread
import pandas as pd
import streamlit as st
from google.oauth2.service_account import Credentials

st.set_page_config(page_title="Marathon Tracker", page_icon="🏃", layout="centered")

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


# ---------------------------------------------------------------- data layer
@st.cache_resource
def get_spreadsheet():
    creds = Credentials.from_service_account_info(
        st.secrets["gcp_service_account"], scopes=SCOPES
    )
    client = gspread.authorize(creds)
    return client.open_by_url(st.secrets["sheet"]["url"])


@st.cache_data(ttl=120)
def load_data() -> tuple[pd.DataFrame, pd.DataFrame]:
    sh = get_spreadsheet()

    plan = pd.DataFrame(sh.worksheet("Plan").get_all_records())
    plan.columns = [c.strip() for c in plan.columns]
    plan["Start Date"] = pd.to_datetime(plan["Start Date"]).dt.date
    plan["Planned Miles"] = pd.to_numeric(plan["Planned Miles"], errors="coerce").fillna(0)
    plan = plan.sort_values("Start Date").reset_index(drop=True)

    runs_ws = sh.worksheet("Runs")
    runs = pd.DataFrame(runs_ws.get_all_records())
    if runs.empty:
        runs = pd.DataFrame(columns=["Date", "Miles", "Note"])
    runs.columns = [c.strip() for c in runs.columns]
    runs["Date"] = pd.to_datetime(runs["Date"]).dt.date
    runs["Miles"] = pd.to_numeric(runs["Miles"], errors="coerce").fillna(0)
    return plan, runs


def add_run(run_date: date, miles: float, note: str) -> None:
    sh = get_spreadsheet()
    sh.worksheet("Runs").append_row(
        [run_date.isoformat(), miles, note], value_input_option="USER_ENTERED"
    )
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
        "Couldn't load the Google Sheet. Check that the sheet is shared with the "
        "service-account email and the secrets are set.\n\n"
        f"Details: {exc}"
    )
    st.stop()

if plan.empty:
    st.warning("The Plan tab is empty. Add rows: Week | Start Date | Planned Miles.")
    st.stop()

today = date.today()
race_date = datetime.fromisoformat(st.secrets["sheet"]["race_date"]).date()
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

    # cumulative through last completed week
    done = weekly.iloc[:cur_idx]
    delta = done["Actual"].sum() - done["Planned Miles"].sum()
    if len(done):
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
            add_run(run_date, miles, note)
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

# ---- week table + recent runs
tab1, tab2 = st.tabs(["Weeks", "Recent runs"])
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
        recent = runs.sort_values("Date", ascending=False).head(20).copy()
        recent["Date"] = recent["Date"].map(lambda d: f"{d:%a %b %d}")
        st.dataframe(recent, hide_index=True, use_container_width=True)
    st.caption("To edit or delete a run, change the row directly in the Google Sheet.")

if st.button("↻ Refresh from sheet"):
    load_data.clear()
    st.rerun()
