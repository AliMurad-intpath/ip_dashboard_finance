"""Accounting sign conventions and age buckets; independent of the ORM."""
INCOME = ('income', 'income_other')
EXPENSE = ('expense', 'expense_direct_cost', 'expense_depreciation')
ASSET = ('asset_receivable', 'asset_cash', 'asset_current', 'asset_non_current', 'asset_prepayments', 'asset_fixed')
LIABILITY = ('liability_payable', 'liability_credit_card', 'liability_current', 'liability_non_current')
EQUITY = ('equity', 'equity_unaffected')

def totals(balances):
    total = lambda types: sum(balances.get(t, 0.0) for t in types)
    revenue = -total(INCOME)
    costs = total(('expense_direct_cost',))
    expenses = total(('expense', 'expense_depreciation'))
    profit = revenue - costs - expenses
    return dict(revenue=revenue, cogs=costs, expenses=expenses,
                gross_profit=revenue-costs, net_profit=profit,
                net_margin=profit/revenue*100 if revenue else 0.0,
                cash=total(('asset_cash',)), assets=total(ASSET),
                liabilities=-total(LIABILITY), equity=-total(EQUITY),
                earnings=profit, equity_earnings=-total(EQUITY)+profit,
                balance_check=total(ASSET)+total(LIABILITY)+total(EQUITY)-profit)

def age_bucket(due, today):
    days = (today-due).days
    if days <= 0: return 0
    if days <= 30: return 1
    if days <= 60: return 2
    if days <= 90: return 3
    return 4
