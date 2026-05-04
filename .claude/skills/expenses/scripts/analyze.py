"""
Standard analyses for a consolidated Lifestyle Expenses CSV.

Each analysis is a function that takes a DataFrame and returns either a
DataFrame (for tables) or a string (for printed summaries).

Usage from a prompt:
    python -c "
    import pandas as pd
    from analyze import *
    df = pd.read_csv('Lifestyle Expenses.csv')
    print(ttm_summary(df))
    print(category_by_person(df))
    "

Or just import and call individual functions in a notebook session.
"""
import pandas as pd


def _ttm_filter(df, period_end=None):
    end = pd.Timestamp(period_end) if period_end else pd.Timestamp.today()
    start = end - pd.DateOffset(years=1)
    df = df.copy()
    df['_dt'] = pd.to_datetime(df['Date'])
    return df[(df['_dt'] >= start) & (df['_dt'] <= end)].drop(columns=['_dt'])


def ttm_summary(df, period_end=None):
    """Last-12-months total + category roll-up."""
    ttm = _ttm_filter(df, period_end)
    total = ttm['Amount'].sum()
    by_cat = (ttm.groupby('Category')['Amount']
                .agg(txns='count', total='sum')
                .sort_values('total', ascending=False))
    by_cat['pct'] = (by_cat['total'] / total * 100).round(1)
    by_cat['total'] = by_cat['total'].round(0)
    return f"Last 12 months total: ${total:,.0f} across {len(ttm):,} transactions\n\n{by_cat.to_string()}"


def category_by_person(df, period_end=None):
    """Category x Person pivot (Person inferred from first word of Source)."""
    ttm = _ttm_filter(df, period_end)
    ttm = ttm.copy()
    ttm['Person'] = ttm['Source'].str.split().str[0]
    pivot = ttm.pivot_table(index='Category', columns='Person',
                            values='Amount', aggfunc='sum', fill_value=0).round(0)
    pivot['Total'] = pivot.sum(axis=1)
    return pivot.sort_values('Total', ascending=False)


def drill_down(df, category, period_end=None, top_n=30):
    """Top N transactions in a given category by amount."""
    ttm = _ttm_filter(df, period_end)
    sub = ttm[ttm['Category'] == category].sort_values('Amount', ascending=False)
    return sub.head(top_n)


def subcategory_breakdown(df, category, period_end=None):
    """Subcategory totals within a category."""
    ttm = _ttm_filter(df, period_end)
    sub = ttm[ttm['Category'] == category]
    return (sub.groupby('Subcategory')['Amount']
            .agg(txns='count', total='sum')
            .sort_values('total', ascending=False).round(0))


def trip_clusters(df, gap_days=7, period_end=None,
                  include_extras=True, extras_window=2):
    """Cluster Travel transactions into discrete trips, then optionally
    pull in non-Travel charges that happened during each trip window
    AS LONG AS those merchants don't look like home-base routine spend.

    A "home-base merchant" is one that appears in 5+ distinct months of
    the year — daily coffee, work cafeteria, regular grocery, monthly
    autopays. Including those in trip totals inflates the numbers.

    Args:
        gap_days: max gap between Travel charges to stay in same trip
        include_extras: also count non-Travel one-off charges in trip window
        extras_window: pad trip date range by this many days on each side
    """
    ttm = _ttm_filter(df, period_end)
    travel = ttm[ttm['Category'] == 'Travel'].copy()
    travel['_dt'] = pd.to_datetime(travel['Date'])
    travel = travel.sort_values('_dt')
    travel['gap'] = travel['_dt'].diff().dt.days.fillna(99)
    travel['trip_id'] = (travel['gap'] > gap_days).cumsum()

    # Identify home-base merchants (appear in 5+ months → routine, not trip-bound)
    ttm = ttm.copy()
    ttm['_dt'] = pd.to_datetime(ttm['Date'])
    ttm['_month'] = ttm['_dt'].dt.to_period('M')
    months_per_desc = (ttm.groupby(ttm['Description'].fillna(''))['_month']
                         .nunique())
    home_base = set(months_per_desc[months_per_desc >= 5].index)

    def label(group):
        return group.loc[group['Amount'].idxmax(), 'Description']

    trips = (travel.groupby('trip_id')
             .agg(start=('_dt', 'min'),
                  end=('_dt', 'max'),
                  travel_total=('Amount', 'sum'),
                  travel_n=('Amount', 'count')))
    trips['label'] = travel.groupby('trip_id').apply(label, include_groups=False)

    if include_extras:
        extras_total = []
        extras_n = []
        for tid, row in trips.iterrows():
            window_start = row['start'] - pd.Timedelta(days=extras_window)
            window_end = row['end'] + pd.Timedelta(days=extras_window)
            in_window = ttm[(ttm['_dt'] >= window_start) &
                            (ttm['_dt'] <= window_end) &
                            (ttm['Category'] != 'Travel')]
            non_routine = in_window[~in_window['Description'].fillna('').isin(home_base)]
            extras_total.append(non_routine['Amount'].sum())
            extras_n.append(len(non_routine))
        trips['extras_total'] = extras_total
        trips['extras_n'] = extras_n
        trips['total'] = trips['travel_total'] + trips['extras_total']
    else:
        trips['total'] = trips['travel_total']

    trips = trips.round(0)
    return trips.sort_values('total', ascending=False)


def recurring_subscriptions(df, min_count=6, period_end=None):
    """Find merchants that hit ≥N times in TTM."""
    ttm = _ttm_filter(df, period_end)
    subs = ttm[ttm['Category'] == 'Subscriptions & Software']
    recur = (subs.groupby('Description')
             .agg(n=('Amount', 'count'),
                  total=('Amount', 'sum'),
                  avg=('Amount', 'mean'))
             .round(2))
    return recur[recur['n'] >= min_count].sort_values('total', ascending=False)


def big_transactions(df, threshold=1000, period_end=None):
    """Single transactions ≥ $threshold for spot-checking."""
    ttm = _ttm_filter(df, period_end)
    big = ttm[ttm['Amount'].abs() >= threshold].sort_values('Amount', ascending=False)
    return big


def yoy_change(df, period_end=None):
    """Year-over-year change by category."""
    end = pd.Timestamp(period_end) if period_end else pd.Timestamp.today()
    df = df.copy()
    df['_dt'] = pd.to_datetime(df['Date'])
    ttm = df[(df['_dt'] >= end - pd.DateOffset(years=1)) & (df['_dt'] <= end)]
    prior = df[(df['_dt'] >= end - pd.DateOffset(years=2)) & (df['_dt'] < end - pd.DateOffset(years=1))]

    ttm_by_cat = ttm.groupby('Category')['Amount'].sum()
    prior_by_cat = prior.groupby('Category')['Amount'].sum()
    delta = pd.DataFrame({'TTM': ttm_by_cat, 'Prior': prior_by_cat}).fillna(0).round(0)
    delta['$ change'] = (delta['TTM'] - delta['Prior']).round(0)
    delta['% change'] = ((delta['TTM'] / delta['Prior'].replace(0, 1) - 1) * 100).round(0)
    return delta.sort_values('$ change', ascending=False)


def misc_review(df, top_n=30, period_end=None):
    """Top Misc rows for user review."""
    ttm = _ttm_filter(df, period_end)
    misc = ttm[ttm['Category'] == 'Misc'].sort_values('Amount', ascending=False)
    return misc.head(top_n)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('csv')
    parser.add_argument('--analysis', default='summary',
                        choices=['summary', 'person', 'trips', 'subs', 'big', 'yoy', 'misc'])
    parser.add_argument('--category', help='for drill-down / subcat')
    parser.add_argument('--period-end')
    args = parser.parse_args()

    df = pd.read_csv(args.csv)
    pe = args.period_end

    if args.analysis == 'summary':
        print(ttm_summary(df, pe))
    elif args.analysis == 'person':
        print(category_by_person(df, pe).to_string())
    elif args.analysis == 'trips':
        print(trip_clusters(df, period_end=pe).to_string())
    elif args.analysis == 'subs':
        print(recurring_subscriptions(df, period_end=pe).to_string())
    elif args.analysis == 'big':
        print(big_transactions(df, period_end=pe).to_string())
    elif args.analysis == 'yoy':
        print(yoy_change(df, pe).to_string())
    elif args.analysis == 'misc':
        print(misc_review(df, period_end=pe).to_string())
