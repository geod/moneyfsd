"""Generate editorial-style spending charts from a Lifestyle Expenses CSV.

Usage:
    python charts.py "Lifestyle Expenses.csv" [--out chart_dir/]

Renders 10 PNGs:
   1. Categories (horizontal bar with shares)
   2. Monthly stacked by major categories
   3. Person split by category
   4. Cumulative spend over time
   5. Housing subcategory breakdown
   6. Travel subcategory breakdown
   7. Travel monthly rollup
   8. Kids subcategory breakdown
   9. Food & Dining subcategory breakdown
  10. Holiday Home subcategory breakdown

Style: cream background, muted editorial palette, Georgia serif title,
horizontal-only gridlines, kicker rule above title.
"""
import argparse
from pathlib import Path

import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.ticker as mtick
from matplotlib.patches import Rectangle


# ============================================================
# DESIGN SYSTEM
# ============================================================
BG       = '#FBF7F0'
INK      = '#161616'
INK_DIM  = '#8A8278'
HAIRLINE = '#E8DFD0'
RULE     = '#C4623E'

CATEGORY_COLORS = {
    'Housing':                  '#264653',
    'Travel':                   '#C4623E',
    'Kids':                     '#E2A150',
    'Holiday Home':             '#C9A961',
    'Food & Dining':            '#3D5A6C',
    'Shopping & Retail':        '#9C7BB6',
    'Home Services':            '#6B9080',
    'Auto & Transport':         '#A87C3F',
    'Sports & Hobbies':         '#A8B85A',
    'Cash':                     '#C66E84',
    'Personal Care & Fitness':  '#5E7A8C',
    'Health':                   '#B45253',
    'Subscriptions & Software': '#4A8A92',
    'Insurance':                '#7CA982',
    'Misc':                     '#A38AC1',
    'Pets':                     '#5C6B73',
    'Entertainment':            '#D88C9A',
    'Professional Services':    '#7AA1B9',
    'Fees':                     '#D49A6E',
    'Charity & Gifts':          '#A8A29E',
    'Other':                    '#C8BFB1',
}
# Person palette — applied positionally to whichever names are detected
# in the data. The first person discovered gets the first colour, etc.
PERSON_PALETTE = ['#264653', '#C4623E', '#6B9080', '#A87C3F', '#9C7BB6']
SUB_PALETTE = [
    '#C4623E', '#E2A150', '#C9A961', '#6B9080', '#9C7BB6',
    '#4A8A92', '#A8B85A', '#B45253', '#7AA1B9', '#A38AC1',
    '#D88C9A', '#5E7A8C', '#7CA982', '#D49A6E', '#A8A29E',
]


def _setup_rc():
    plt.rcParams.update({
        'figure.facecolor': BG, 'axes.facecolor': BG, 'savefig.facecolor': BG,
        'font.family': ['Helvetica Neue', 'Helvetica', 'Arial', 'sans-serif'],
        'font.size': 10.5,
        'text.color': INK, 'axes.labelcolor': INK_DIM,
        'axes.edgecolor': HAIRLINE, 'axes.linewidth': 0,
        'axes.spines.top': False, 'axes.spines.right': False,
        'axes.spines.left': False, 'axes.spines.bottom': False,
        'axes.grid': True, 'axes.axisbelow': True,
        'grid.color': HAIRLINE, 'grid.linewidth': 0.7, 'grid.alpha': 0.9,
        'xtick.color': INK_DIM, 'ytick.color': INK_DIM,
        'xtick.major.size': 0, 'ytick.major.size': 0,
        'legend.frameon': False, 'legend.fontsize': 10,
    })


def usd(x, _=None):
    if abs(x) >= 1_000_000: return f'${x/1_000_000:.1f}M'
    if abs(x) >= 1_000: return f'${x/1000:.0f}k'
    return f'${x:.0f}'


def _color_for(category):
    return CATEGORY_COLORS.get(category, '#C8BFB1')


def _style_axes(ax):
    ax.grid(axis='y', color=HAIRLINE, linewidth=0.7, alpha=0.9)
    ax.grid(axis='x', visible=False)
    ax.set_axisbelow(True)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.tick_params(axis='both', length=0)


def _add_title_block(fig, title, subtitle=None, kicker=None):
    fig.patches.append(Rectangle((0.06, 0.965), 0.06, 0.006,
                                 transform=fig.transFigure,
                                 color=RULE, zorder=10))
    if kicker:
        fig.text(0.06, 0.945, '  '.join(kicker.upper()), fontsize=9.5,
                 color=RULE, fontweight='bold', ha='left', va='top',
                 parse_math=False)
        title_y = 0.910
    else:
        title_y = 0.945
    fig.text(0.06, title_y, title, fontsize=22, fontweight='bold', color=INK,
             ha='left', va='top', family='Georgia', parse_math=False)
    if subtitle:
        fig.text(0.06, title_y - 0.055, subtitle, fontsize=12, color=INK_DIM,
                 ha='left', va='top', parse_math=False)


def _add_footer(fig, text):
    fig.text(0.06, 0.02, text, fontsize=8.5, color=INK_DIM,
             ha='left', va='bottom', alpha=0.85, parse_math=False)


def _person_from_source(source, people):
    """Map a Source string to a person by case-insensitive substring match.
    `people` is the ordered list of person names from the config.
    Returns the matched person name (preserving case from `people`), or '?'."""
    s = str(source or '').lower()
    for p in people:
        if p.lower() in s:
            return p
    return '?'


# ============================================================
# Chart functions
# ============================================================
def chart_categories(df, out_dir, footer):
    totals = df.groupby('Category')['Amount'].sum().sort_values(ascending=True)
    total = totals.sum()
    shares = totals / total * 100
    fig, ax = plt.subplots(figsize=(11.5, 9.5))
    fig.subplots_adjust(left=0.24, right=0.94, top=0.82, bottom=0.08)
    ax.barh(totals.index, totals.values,
            color=[_color_for(c) for c in totals.index],
            height=0.74, edgecolor='none')
    for i, (cat, val) in enumerate(totals.items()):
        ax.text(val + totals.max()*0.012, i, usd(val),
                va='center', fontsize=10.5, fontweight='bold', color=INK)
        ax.text(val + totals.max()*0.105, i, f'{shares[cat]:.1f}%',
                va='center', fontsize=9.5, color=INK_DIM)
    ax.xaxis.set_major_formatter(mtick.FuncFormatter(usd))
    ax.set_xlim(0, totals.max() * 1.30)
    ax.tick_params(axis='y', labelsize=10.5, pad=6)
    _style_axes(ax)
    _add_title_block(fig, 'Spending by category',
                     'Where money flowed over the period', kicker='Annual review')
    _add_footer(fig, footer)
    plt.savefig(out_dir / 'chart_1_categories.png', dpi=180, bbox_inches='tight', facecolor=BG)
    plt.close()


def chart_monthly(df, out_dir, footer):
    totals = df.groupby('Category')['Amount'].sum().sort_values(ascending=False)
    top = totals.head(8).index.tolist()
    mom = df.pivot_table(index='Month', columns='Category',
                         values='Amount', aggfunc='sum', fill_value=0)
    mom['Other'] = mom[[c for c in mom.columns if c not in top]].sum(axis=1)
    mom = mom[top + ['Other']].sort_index()
    fig, ax = plt.subplots(figsize=(14, 7.8))
    fig.subplots_adjust(left=0.06, right=0.97, top=0.78, bottom=0.10)
    bottoms = [0] * len(mom.index)
    x = list(range(len(mom.index)))
    for cat in top + ['Other']:
        ax.bar(x, mom[cat], bottom=bottoms, label=cat,
               color=_color_for(cat), width=0.78, edgecolor='none')
        bottoms = [b + v for b, v in zip(bottoms, mom[cat])]
    ax.yaxis.set_major_formatter(mtick.FuncFormatter(usd))
    peak = max(mom.sum(axis=1))
    for i in range(len(mom.index)):
        t = mom.iloc[i].sum()
        ax.text(i, t + peak*0.022, f'${t/1000:.0f}k', ha='center',
                fontsize=10, fontweight='bold', color=INK)
    ax.set_ylim(0, peak * 1.15); ax.set_xlim(-0.5, len(x)-0.5)
    ax.set_xticks(x)
    ax.set_xticklabels([pd.Period(m).strftime('%b %y') for m in mom.index], fontsize=10)
    ax.legend(loc='upper left', ncol=5, frameon=False, fontsize=10,
              bbox_to_anchor=(0.0, 1.10), columnspacing=1.6,
              handlelength=1.0, handleheight=0.9, handletextpad=0.5)
    _style_axes(ax)
    _add_title_block(fig, 'Monthly spend by category',
                     'Stacked. Total above each bar.', kicker='Annual review')
    _add_footer(fig, footer)
    plt.savefig(out_dir / 'chart_2_monthly.png', dpi=180, bbox_inches='tight', facecolor=BG)
    plt.close()


def chart_person(df, out_dir, footer):
    pc = df.pivot_table(index='Category', columns='Person',
                        values='Amount', aggfunc='sum', fill_value=0)
    # Use whichever named people the data contains (skip the '?' bucket).
    people = [c for c in pc.columns if c != '?']
    if len(people) < 2:
        return  # need at least two people to make a comparison meaningful
    if len(people) > len(PERSON_PALETTE):
        people = people[:len(PERSON_PALETTE)]  # cap at palette size
    pc['Total'] = pc[people].sum(axis=1)
    pc = pc.sort_values('Total', ascending=True).drop(columns='Total')
    fig, ax = plt.subplots(figsize=(11.5, 10.5))
    fig.subplots_adjust(left=0.24, right=0.94, top=0.84, bottom=0.07)
    y = list(range(len(pc.index)))
    n = len(people)
    bar_h = 0.8 / n
    offsets = [(i - (n - 1) / 2) * bar_h for i in range(n)]
    for i, p in enumerate(people):
        ax.barh([yi + offsets[i] for yi in y], pc[p], height=bar_h,
                color=PERSON_PALETTE[i], label=p, edgecolor='none')
    ax.set_yticks(y); ax.set_yticklabels(pc.index, fontsize=10.5)
    ax.xaxis.set_major_formatter(mtick.FuncFormatter(usd))
    ax.legend(loc='lower right', fontsize=11, frameon=False,
              handletextpad=0.6, borderpad=0.4)
    _style_axes(ax)
    totals = ' · '.join(f'{p} ${pc[p].sum()/1000:.0f}k' for p in people)
    _add_title_block(fig, 'Who spends what',
                     f'{totals} — by category', kicker='Annual review')
    _add_footer(fig, footer)
    plt.savefig(out_dir / 'chart_3_person.png', dpi=180, bbox_inches='tight', facecolor=BG)
    plt.close()


def chart_cumulative(df, out_dir, footer):
    daily = df.groupby('Date')['Amount'].sum().sort_index()
    cum = daily.cumsum()
    total = cum.iloc[-1]
    fig, ax = plt.subplots(figsize=(14, 6.5))
    fig.subplots_adjust(left=0.06, right=0.97, top=0.78, bottom=0.10)
    ax.fill_between(cum.index, cum.values, alpha=0.15, color=_color_for('Housing'))
    ax.plot(cum.index, cum.values, color=_color_for('Housing'), linewidth=2.4)
    ax.yaxis.set_major_formatter(mtick.FuncFormatter(usd))
    for d, amt in daily.nlargest(8).items():
        ax.scatter([d], [cum.loc[d]], color=RULE, s=48, zorder=5,
                   edgecolor=BG, linewidth=2.5)
        ax.annotate(f'${amt/1000:.0f}k', (d, cum.loc[d]),
                    xytext=(8, -14), textcoords='offset points',
                    fontsize=9.5, color=RULE, fontweight='bold')
    _style_axes(ax)
    _add_title_block(fig, 'Cumulative spend',
                     f'Running total reaches ${total/1000:.0f}k. Dots mark eight biggest single days.',
                     kicker='Annual review')
    _add_footer(fig, footer)
    plt.savefig(out_dir / 'chart_4_cumulative.png', dpi=180, bbox_inches='tight', facecolor=BG)
    plt.close()


def chart_subcategory(df, category, filename, palette_offset=0,
                      subtitle_extra=None, out_dir=None, footer=''):
    sub = df[df['Category'] == category].copy()
    if sub.empty:
        return
    months = sorted(df['Month'].unique())
    pivot = sub.pivot_table(index='Month', columns='Subcategory',
                            values='Amount', aggfunc='sum',
                            fill_value=0).reindex(months, fill_value=0)
    order = pivot.sum().sort_values(ascending=False).index.tolist()
    pivot = pivot[order]
    fig, ax = plt.subplots(figsize=(14, 7))
    fig.subplots_adjust(left=0.06, right=0.97, top=0.78, bottom=0.10)
    bottoms = [0] * len(pivot.index)
    sub_colors = [_color_for(category)] + [
        SUB_PALETTE[(palette_offset + i) % len(SUB_PALETTE)] for i in range(len(order)-1)
    ]
    x = list(range(len(pivot.index)))
    for i, sc in enumerate(order):
        ax.bar(x, pivot[sc], bottom=bottoms, label=sc,
               color=sub_colors[i], width=0.78, edgecolor='none')
        bottoms = [b + v for b, v in zip(bottoms, pivot[sc])]
    total = sub['Amount'].sum()
    peak = max(pivot.sum(axis=1))
    ax.yaxis.set_major_formatter(mtick.FuncFormatter(usd))
    ax.legend(loc='upper left', ncol=min(4, len(order)),
              frameon=False, bbox_to_anchor=(0.0, 1.10),
              fontsize=10, columnspacing=1.6,
              handlelength=1.0, handleheight=0.9, handletextpad=0.5)
    ax.set_xticks(x)
    ax.set_xticklabels([pd.Period(m).strftime('%b %y') for m in pivot.index], fontsize=10)
    for i in range(len(pivot.index)):
        t = pivot.iloc[i].sum()
        if t > 0:
            ax.text(i, t + peak*0.022, f'${t/1000:.1f}k', ha='center',
                    fontsize=9.5, fontweight='bold', color=INK)
    ax.set_ylim(0, peak * 1.15); ax.set_xlim(-0.5, len(x)-0.5)
    _style_axes(ax)
    sub_text = f'${total:,.0f} over the period — by subcategory'
    if subtitle_extra:
        sub_text += '. ' + subtitle_extra
    _add_title_block(fig, category, sub_text, kicker='Annual review')
    _add_footer(fig, footer)
    plt.savefig(out_dir / filename, dpi=180, bbox_inches='tight', facecolor=BG)
    plt.close()


def chart_travel_monthly(df, out_dir, footer):
    travel = df[df['Category'] == 'Travel']
    if travel.empty: return
    monthly = travel.groupby('Month')['Amount'].sum().sort_index()
    fig, ax = plt.subplots(figsize=(13, 6.2))
    fig.subplots_adjust(left=0.06, right=0.97, top=0.78, bottom=0.12)
    x = list(range(len(monthly.index)))
    bars = ax.bar(x, monthly.values, color=_color_for('Travel'),
                  width=0.7, edgecolor='none')
    ax.yaxis.set_major_formatter(mtick.FuncFormatter(usd))
    peak = monthly.max()
    for bar in bars:
        h = bar.get_height()
        if h > 500:
            ax.text(bar.get_x() + bar.get_width()/2, h + peak*0.025,
                    f'${h/1000:.1f}k', ha='center', fontsize=10,
                    fontweight='bold', color=INK)
    ax.set_xticks(x)
    ax.set_xticklabels([pd.Period(m).strftime('%b %y') for m in monthly.index], fontsize=10)
    ax.set_ylim(0, peak * 1.18); ax.set_xlim(-0.5, len(x)-0.5)
    _style_axes(ax)
    _add_title_block(fig, 'Travel by month',
                     f'${monthly.sum():,.0f} over the period — concentrated in trip months.',
                     kicker='Annual review')
    _add_footer(fig, footer)
    plt.savefig(out_dir / 'chart_7_travel_monthly.png', dpi=180, bbox_inches='tight', facecolor=BG)
    plt.close()


def chart_sankey(df, out_dir, footer, top_categories=8, top_subs_per_cat=4):
    """Three-level Sankey: Person → Category → Subcategory, as HTML.

    Always three columns. With one person, the Person column is a single
    trunk that fans into categories — still useful as a visual anchor.
    Skips silently if plotly isn't installed.

    Defaults aim for readability:
      - Top `top_categories` categories shown directly; the rest collapse
        into a single "Other categories" node.
      - Top `top_subs_per_cat` subcategories per category; the rest collapse
        into a per-category "Other".
      - Categories sorted by total spend descending. Subs sorted by their
        parent category's vertical position so ribbons don't cross at the
        third level. People sorted by total spend descending.
    """
    try:
        import plotly.graph_objects as go
    except ImportError:
        print("  (Skipping Sankey — install plotly to enable: pip install plotly)")
        return

    work = df[df['Amount'] > 0].copy()
    if work.empty: return
    work['Subcategory'] = work['Subcategory'].fillna('—')
    work['Person'] = work['Person'].fillna('?')

    cat_totals = (work.groupby('Category')['Amount'].sum()
                      .sort_values(ascending=False))
    keep_cats = list(cat_totals.head(top_categories).index)
    work['_cat'] = work['Category'].where(
        work['Category'].isin(keep_cats), 'Other categories')

    keep_subs = {}
    for c in keep_cats:
        subs = (work[work['_cat'] == c].groupby('Subcategory')['Amount']
                                       .sum().sort_values(ascending=False))
        keep_subs[c] = set(subs.head(top_subs_per_cat).index)

    def map_sub(row):
        c = row['_cat']
        if c == 'Other categories':
            return '(rolled up)'
        return row['Subcategory'] if row['Subcategory'] in keep_subs.get(c, set()) else 'Other'

    work['_sub'] = work.apply(map_sub, axis=1)
    flows = (work.groupby(['Person', '_cat', '_sub'])['Amount']
                 .sum().reset_index()
                 .rename(columns={'_cat': 'Category', '_sub': 'Subcategory'}))

    # Build node columns. People sorted by spend; categories sorted by spend;
    # subs sorted by parent category's vertical position so third-level
    # ribbons don't cross.
    people_nodes = list(flows.groupby('Person')['Amount'].sum()
                             .sort_values(ascending=False).index)
    cat_nodes = list(flows.groupby('Category')['Amount'].sum()
                          .sort_values(ascending=False).index)
    cat_order = {c: i for i, c in enumerate(cat_nodes)}
    sub_keys = (flows.assign(key=flows['Category'] + ' · ' + flows['Subcategory'])
                     .groupby(['Category', 'key'])['Amount'].sum()
                     .reset_index())
    sub_keys['_cat_rank'] = sub_keys['Category'].map(cat_order)
    sub_keys = sub_keys.sort_values(['_cat_rank', 'Amount'],
                                    ascending=[True, False])
    sub_nodes = list(sub_keys['key'])

    nodes = people_nodes + cat_nodes + sub_nodes
    node_index = {n: i for i, n in enumerate(nodes)}

    def hex_to_rgba(h, alpha=0.55):
        h = h.lstrip('#')
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        return f'rgba({r},{g},{b},{alpha})'

    person_color = '#6B7280'
    cat_colors = [_color_for(c) for c in cat_nodes]
    sub_colors = [_color_for(k.split(' · ')[0]) for k in sub_nodes]
    node_colors = [person_color] * len(people_nodes) + cat_colors + sub_colors

    src, tgt, val, link_color = [], [], [], []
    for (p, c), amt in flows.groupby(['Person', 'Category'])['Amount'].sum().items():
        src.append(node_index[p])
        tgt.append(node_index[c])
        val.append(round(amt, 0))
        link_color.append(hex_to_rgba(_color_for(c), 0.45))
    for _, row in flows.iterrows():
        key = f"{row['Category']} · {row['Subcategory']}"
        src.append(node_index[row['Category']])
        tgt.append(node_index[key])
        val.append(round(row['Amount'], 0))
        link_color.append(hex_to_rgba(_color_for(row['Category']), 0.55))

    display_labels = (people_nodes + cat_nodes +
                      [k.split(' · ', 1)[1] for k in sub_nodes])

    fig = go.Figure(go.Sankey(
        arrangement='snap',
        node=dict(label=display_labels, color=node_colors,
                  pad=14, thickness=18,
                  line=dict(color='rgba(0,0,0,0)', width=0)),
        link=dict(source=src, target=tgt, value=val, color=link_color),
    ))
    fig.update_layout(
        title=dict(
            text=f"<b style='font-family:Georgia'>Where the money flowed</b>"
                 f"<br><span style='color:#8A8278;font-size:14px'>{footer}</span>",
            x=0.04, y=0.96, xanchor='left',
            font=dict(family='Helvetica Neue, Helvetica, Arial', size=22, color='#161616'),
        ),
        font=dict(family='Helvetica Neue, Helvetica, Arial', size=12, color='#161616'),
        paper_bgcolor=BG, plot_bgcolor=BG,
        margin=dict(l=24, r=24, t=110, b=24),
        height=900,
    )
    output_path = out_dir / 'chart_11_sankey.html'
    fig.write_html(output_path, include_plotlyjs='cdn',
                   config={'displayModeBar': False})
    print(f"  Sankey: {output_path}")


def _discover_people(df, config_people=None):
    """Pick person names. Prefer the explicit list from `people:` in
    expenses_config.yaml. Otherwise infer from the first whitespace-separated
    token of each Source value (e.g., 'Alex AmEx' → 'Alex')."""
    if config_people:
        return list(config_people)
    tokens = (df['Source'].fillna('').str.split().str[0]
                          .replace('', pd.NA).dropna().unique())
    return list(tokens)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('csv')
    parser.add_argument('--config', help='Optional expenses_config.yaml — uses '
                                         "its `people:` list for chart attribution")
    parser.add_argument('--out', help='Output directory (defaults to CSV folder)')
    args = parser.parse_args()

    csv_path = Path(args.csv).resolve()
    out_dir = Path(args.out).resolve() if args.out else csv_path.parent

    config_people = None
    if args.config:
        try:
            import yaml
            with open(args.config) as f:
                config_people = yaml.safe_load(f).get('people')
        except Exception:
            config_people = None

    _setup_rc()
    df = pd.read_csv(csv_path)
    df['Date'] = pd.to_datetime(df['Date'], format='%m/%d/%Y')
    df['Month'] = df['Date'].dt.to_period('M').astype(str)
    people = _discover_people(df, config_people)
    df['Person'] = df['Source'].apply(lambda s: _person_from_source(s, people))

    period_start = df['Date'].min().strftime('%b %Y')
    period_end = df['Date'].max().strftime('%b %Y')
    footer = (f"{period_start} → {period_end}  ·  {len(df):,} transactions  ·  "
              f"${df['Amount'].sum():,.0f} total")

    chart_categories(df, out_dir, footer)
    chart_monthly(df, out_dir, footer)
    chart_person(df, out_dir, footer)
    chart_cumulative(df, out_dir, footer)
    chart_subcategory(df, 'Housing', 'chart_5_housing_sub.png',
                       palette_offset=2, out_dir=out_dir, footer=footer)
    chart_subcategory(df, 'Travel', 'chart_6_travel_sub.png',
                       palette_offset=5, out_dir=out_dir, footer=footer)
    chart_travel_monthly(df, out_dir, footer)
    chart_subcategory(df, 'Kids', 'chart_8_kids_sub.png',
                       palette_offset=8, out_dir=out_dir, footer=footer)
    chart_subcategory(df, 'Food & Dining', 'chart_9_food_sub.png',
                       palette_offset=11, out_dir=out_dir, footer=footer)
    chart_subcategory(df, 'Holiday Home', 'chart_10_holiday_home_sub.png',
                       palette_offset=13, out_dir=out_dir, footer=footer)
    chart_sankey(df, out_dir, footer)
    print(f"Saved charts to {out_dir}")


if __name__ == '__main__':
    main()
