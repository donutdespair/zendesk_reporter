# utils/plotting.py
import matplotlib.pyplot as plt
import seaborn as sns
import pandas as pd
import streamlit as st
import numpy as np # Import numpy for binning if needed

# --- Set plot style ---
sns.set_style("whitegrid")
plt.rcParams['figure.dpi'] = 100
plt.rcParams['savefig.bbox'] = 'tight'

# --- plot_tickets_by_status function (remains the same) ---
def plot_tickets_by_status(df):
    """Generates a countplot of tickets by status."""
    plot_area = st.empty()
    if 'status' not in df.columns or df['status'].isnull().all(): plot_area.warning("Plotting Error: Status column missing/empty."); return None
    fig, ax = plt.subplots(figsize=(10, 6))
    try:
        status_counts = df['status'].value_counts();
        if status_counts.empty: plot_area.warning("Plotting Error: No data for status."); plt.close(fig); return None
        sns.countplot(data=df, y='status', order=status_counts.index, palette="viridis", ax=ax)
        ax.set_title('Number of Tickets by Status'); ax.set_xlabel('Number of Tickets'); ax.set_ylabel('Status')
        for container in ax.containers: ax.bar_label(container, fmt='%.0f')
        ax.set_xlim(right=ax.get_xlim()[1] * 1.1); fig.tight_layout()
    except Exception as e: plot_area.error(f"Error generating status plot: {e}"); plt.close(fig); return None
    return fig

# --- plot_tickets_per_day function (remains the same) ---
def plot_tickets_per_day(df):
    """Generates a line plot of tickets created per day."""
    plot_area = st.empty()
    if 'created_at' not in df.columns or not pd.api.types.is_datetime64_any_dtype(df['created_at']): plot_area.warning("Plotting Error: Valid 'created_at' column missing."); return None
    fig, ax = plt.subplots(figsize=(12, 6))
    try:
        df_temp = df.set_index('created_at');
        if not isinstance(df_temp.index, pd.DatetimeIndex): plot_area.warning("Plotting Error: Index not DatetimeIndex."); plt.close(fig); return None
        tickets_per_day = df_temp.sort_index().resample('D').size() # Ensure sorted index
        if tickets_per_day.empty: plot_area.warning("Plotting Error: No data for tickets per day."); plt.close(fig); return None
        tickets_per_day.plot(kind='line', marker='.', linestyle='-', ax=ax, legend=False)
        ax.set_title('Tickets Created Per Day (within filter)'); ax.set_xlabel('Date'); ax.set_ylabel('Number of Tickets Created')
        ax.grid(True, which='both', linestyle='--', linewidth=0.5); fig.tight_layout()
    except Exception as e: plot_area.error(f"Error generating daily trend plot: {e}"); plt.close(fig); return None
    return fig

# --- plot_internal_external_breakdown function (remains the same) ---
def plot_internal_external_breakdown(df):
    """Generates a pie chart showing internal vs external requester breakdown."""
    plot_area = st.empty()
    if 'requester_type' not in df.columns or df['requester_type'].isnull().all(): plot_area.warning("Plotting Error: 'requester_type' column missing/empty."); return None
    fig, ax = plt.subplots(figsize=(8, 6))
    try:
        type_counts = df['requester_type'].value_counts()
        if type_counts.empty: plot_area.warning("Plotting Error: No requester type data."); plt.close(fig); return None
        colors = {'Internal': 'lightblue', 'External': 'lightcoral', 'Unknown': 'lightgrey', 'Not Specified': 'lightgrey'}
        pie_colors = [colors.get(label, 'gray') for label in type_counts.index]
        wedges, texts, autotexts = ax.pie(type_counts, labels=type_counts.index, autopct='%1.1f%%', startangle=140, colors=pie_colors, wedgeprops={"edgecolor": "white", "linewidth": 1})
        ax.set_title('Ticket Breakdown by Requester Type'); plt.setp(autotexts, size=10, weight="bold", color="black"); plt.setp(texts, size=11)
        fig.tight_layout()
    except Exception as e: plot_area.error(f"Error generating requester type plot: {e}"); plt.close(fig); return None
    return fig

# --- plot_resolution_distribution function (remains the same - uses business hours) ---
def plot_resolution_distribution(df, quantile_cutoff=0.98):
    """Generates a histogram of ticket resolution times using BUSINESS HOURS."""
    plot_area = st.empty()
    target_col = 'resolution_time_business_hours'
    if target_col not in df.columns or df[target_col].isnull().all(): plot_area.info("No business hour resolution time data for distribution plot."); return None
    fig, ax = plt.subplots(figsize=(10, 6))
    try:
        resolution_time_filtered = df[target_col].dropna()
        if resolution_time_filtered.empty: plot_area.info("No valid business hour resolution times found."); plt.close(fig); return None
        cutoff_value = None
        if resolution_time_filtered.count() > 0:
             cutoff_value = resolution_time_filtered.quantile(quantile_cutoff)
             if pd.notna(cutoff_value):
                 if cutoff_value > 0: resolution_time_filtered = resolution_time_filtered[resolution_time_filtered <= cutoff_value]
                 else: resolution_time_filtered = resolution_time_filtered[resolution_time_filtered <= 0]
             else: cutoff_value = resolution_time_filtered.max()
        if resolution_time_filtered.empty: plot_area.warning(f"No resolution data remains after filtering >{quantile_cutoff*100:.0f}th percentile."); plt.close(fig); return None
        sns.histplot(resolution_time_filtered, bins=30, kde=True, color="lightgreen", ax=ax)
        title = f'Distribution of Ticket Resolution Time (Business Hours';
        resolution_max = df[target_col].dropna().max()
        if cutoff_value is not None and pd.notna(resolution_max) and cutoff_value < resolution_max: title += f', up to {quantile_cutoff*100:.0f}th Percentile)'
        else: title += ')'
        ax.set_title(title); ax.set_xlabel('Resolution Time (Business Hours)'); ax.set_ylabel('Frequency')
        fig.tight_layout()
    except Exception as e: plot_area.error(f"Error generating resolution distribution plot: {e}"); plt.close(fig); return None
    return fig

# --- plot_median_resolution_by_root_cause function (remains the same - uses business hours) ---
def plot_median_resolution_by_root_cause(df):
    """Generates a Bar Chart showing MEDIAN resolution time (BUSINESS HOURS) by Root Cause."""
    plot_area = st.empty()
    target_col = 'resolution_time_business_hours'; category_col = 'root_cause'
    if category_col not in df.columns or df[category_col].isnull().all(): plot_area.info(f"Cannot plot: '{category_col}' missing/empty."); return None
    if target_col not in df.columns or df[target_col].isnull().all(): plot_area.info(f"Cannot plot: '{target_col}' has no valid data."); return None
    valid_root_causes = df[category_col].dropna(); placeholders = ['Not Specified', 'Unknown', 'Error Processing']
    valid_root_causes = valid_root_causes[~valid_root_causes.isin(placeholders)]; df_plot = df.loc[valid_root_causes.index].copy()
    df_plot = df_plot.dropna(subset=[target_col])
    if df_plot.empty: plot_area.info("No tickets found with valid Resolution Time and specified Root Cause."); return None
    try:
        median_times = df_plot.groupby(category_col, observed=False)[target_col].median().reset_index()
        median_times = median_times.sort_values(by=target_col, ascending=False)
    except Exception as e: plot_area.error(f"Error calculating median times by root cause: {e}"); return None
    if median_times.empty: plot_area.info("Could not calculate median times for any root cause."); return None
    plot_height = max(4, median_times.shape[0] * 0.4); fig, ax = plt.subplots(figsize=(10, plot_height))
    try:
        barplot = sns.barplot(data=median_times, y=category_col, x=target_col, order=median_times[category_col], orient='h', palette='coolwarm_r', ax=ax)
        ax.bar_label(barplot.containers[0], fmt='%.1f hrs', padding=3, fontsize=9)
        ax.set_title('Typical (Median) Resolution Time by Root Cause'); ax.set_xlabel('Median Resolution Time (Business Hours)'); ax.set_ylabel('Root Cause')
        ax.set_xlim(right=median_times[target_col].max() * 1.15); ax.grid(axis='x', linestyle='--', alpha=0.6); fig.tight_layout()
    except Exception as e: plot_area.error(f"Error generating median resolution plot: {e}"); plt.close(fig); return None
    return fig


# --- V V V --- NEW FUNCTION FOR ENGINEERING TICKET AGE --- V V V ---
def plot_engineering_ticket_age(df):
    """
    Generates a histogram showing the age distribution of tickets
    currently in the 'Engineering' custom status.
    """
    plot_area = st.empty()
    engineering_status_id = 26734791021965 # The ID for "Engineering" status
    target_col = 'custom_status_id'
    date_col = 'created_at'

    # Check if required columns exist
    if target_col not in df.columns:
        plot_area.warning("Plotting Error: 'custom_status_id' column missing.")
        return None
    if date_col not in df.columns or not pd.api.types.is_datetime64_any_dtype(df[date_col]):
        plot_area.warning("Plotting Error: Valid 'created_at' column missing.")
        return None

    # Ensure target_col is numeric for comparison
    df_plot = df.copy() # Work on a copy
    df_plot[target_col] = pd.to_numeric(df_plot[target_col], errors='coerce')

    # Filter for tickets currently in 'Engineering' status
    eng_tickets = df_plot[df_plot[target_col] == engineering_status_id].copy()

    if eng_tickets.empty:
        plot_area.info("No tickets currently in 'Engineering' status found within the applied filters.")
        return None

    # Calculate age in days
    try:
        now_utc = pd.Timestamp.now(tz='UTC')
        # Ensure created_at is UTC (should be already from processing)
        if eng_tickets[date_col].dt.tz is None:
            # This shouldn't happen if processing worked, but handle just in case
            st.warning("Localizing created_at to UTC for age calculation.")
            eng_tickets[date_col] = eng_tickets[date_col].dt.tz_localize('UTC', ambiguous='raise')

        # Calculate age and convert timedelta to days (float)
        eng_tickets['age_days'] = (now_utc - eng_tickets[date_col]).dt.total_seconds() / (24 * 3600)
        eng_tickets = eng_tickets.dropna(subset=['age_days']) # Drop if created_at was invalid
        # Handle potential negative ages if clock sync issues exist
        eng_tickets = eng_tickets[eng_tickets['age_days'] >= 0]

    except Exception as e:
        plot_area.error(f"Error calculating ticket age: {e}")
        return None

    if eng_tickets.empty:
        plot_area.info("Could not calculate valid age for any 'Engineering' status tickets.")
        return None

    # Create the histogram
    fig, ax = plt.subplots(figsize=(10, 6))
    try:
        # Define bins for grouping ages
        max_age = eng_tickets['age_days'].max()
        # Create somewhat dynamic bins up to max age found, with specific early bins
        bins = [0, 7, 14, 30, 60, 90, 180]
        if max_age > 180:
            # Add bins up to max_age, maybe in 90 day increments? Or just one final bin
            # Let's add one more bin if max is significantly larger
            if max_age > 365:
                bins.extend([365, max_age + 1])
            else:
                bins.append(max_age + 1)
        bins = sorted(list(set(bins))) # Ensure bins are unique and sorted

        sns.histplot(data=eng_tickets, x='age_days', bins=bins, ax=ax, color='purple', edgecolor='black')

        ax.set_title(f"Age Distribution of Tickets in 'Engineering' Status ({eng_tickets.shape[0]} Tickets)")
        ax.set_xlabel('Age Since Creation (Days)')
        ax.set_ylabel('Number of Tickets')
        ax.grid(axis='y', linestyle='--', alpha=0.7)

        # Add median/average lines
        median_age = eng_tickets['age_days'].median()
        avg_age = eng_tickets['age_days'].mean()
        if pd.notna(median_age):
             ax.axvline(median_age, color='red', linestyle='--', linewidth=1.5, label=f'Median Age: {median_age:.1f} days')
        if pd.notna(avg_age):
             ax.axvline(avg_age, color='black', linestyle=':', linewidth=1.5, label=f'Average Age: {avg_age:.1f} days')

        # Only show legend if at least one line was added
        if pd.notna(median_age) or pd.notna(avg_age):
            ax.legend(fontsize=9)

        # Set x-ticks based on bins for clarity
        ax.set_xticks(bins)
        ax.tick_params(axis='x', rotation=45) # Rotate if labels overlap

        fig.tight_layout()
    except Exception as e:
        plot_area.error(f"Error generating engineering age plot: {e}")
        plt.close(fig); return None

    return fig
# --- ^ ^ ^ --- END NEW FUNCTION --- ^ ^ ^ ---