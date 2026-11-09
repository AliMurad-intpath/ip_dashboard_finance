from datetime import date
from odoo import Command
from odoo.tests import TransactionCase, tagged
from odoo.exceptions import AccessError, ValidationError


@tagged('post_install', '-at_install')
class TestFinanceDashboard(TransactionCase):
    """Run on Odoo.sh staging; does not modify pre-existing business records."""
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env['res.company'].create({'name': 'IP Finance Test Company'})
        cls.provider = cls.env['ip.dashboard.provider'].with_company(cls.company)
        accounts = cls.env['account.account'].with_company(cls.company).create([
            {'name': 'IP test cash', 'code': 'IP100', 'account_type': 'asset_cash', 'company_id': cls.company.id},
            {'name': 'IP test revenue', 'code': 'IP400', 'account_type': 'income', 'company_id': cls.company.id},
            {'name': 'IP test expense', 'code': 'IP600', 'account_type': 'expense', 'company_id': cls.company.id},
        ])
        cls.cash, cls.revenue, cls.expense = accounts
        cls.journal = cls.env['account.journal'].with_company(cls.company).create({
            'name': 'IP test journal', 'code': 'IPT', 'type': 'general', 'company_id': cls.company.id})
        cls.env['account.move'].with_company(cls.company).create({
            'journal_id': cls.journal.id, 'date': date(2026,1,15), 'line_ids': [
                Command.create({'name': 'Cash', 'account_id': cls.cash.id, 'debit': 700}),
                Command.create({'name': 'Expense', 'account_id': cls.expense.id, 'debit': 300}),
                Command.create({'name': 'Revenue', 'account_id': cls.revenue.id, 'credit': 1000}),
            ]}).action_post()
        # Draft entry must not inflate revenue.
        cls.env['account.move'].with_company(cls.company).create({
            'journal_id': cls.journal.id, 'date': date(2026,1,15), 'line_ids': [
                Command.create({'name': 'Cash', 'account_id': cls.cash.id, 'debit': 500}),
                Command.create({'name': 'Revenue', 'account_id': cls.revenue.id, 'credit': 500}),
            ]})

    def metric(self, key, kind='kpi', start='2026-01-01', end='2026-01-31'):
        return self.provider._run_source('finance.'+key, {'kind':kind, 'filters':{}},
            {'period':'custom', 'date_from':start, 'date_to':end}, self.company)

    def test_posted_profit(self):
        self.assertEqual(self.metric('revenue')['value'],1000)
        self.assertEqual(self.metric('net_profit')['value'],700)
        self.assertEqual(self.metric('net_margin')['value'],70)

    def test_closing_includes_opening_balances(self):
        self.assertEqual(self.metric('cash', start='2026-02-01', end='2026-02-28')['value'],700)
        self.assertEqual(self.metric('revenue', start='2026-02-01', end='2026-02-28')['value'],0)

    def test_grouped_balance_sheet(self):
        result=self.metric('balance_sheet','table')
        self.assertEqual([r['value'] for r in result['rows']],[700,0,700])

    def test_non_accounting_user_is_denied(self):
        user=self.env['res.users'].create({'name':'IP non-accountant', 'login':'ip_finance_nonaccountant',
            'company_id':self.company.id, 'company_ids':[Command.set(self.company.ids)],
            'groups_id':[Command.set(self.env.ref('base.group_user').ids)]})
        with self.assertRaises(AccessError):
            self.provider.with_user(user)._run_source('finance.revenue',{'kind':'kpi','filters':{}},{'period':'all'},self.company)

    def test_invalid_filter_rejected(self):
        with self.assertRaises(ValidationError):
            self.provider._run_source('finance.revenue', {'kind':'kpi','filters':{'group_by':'private_field'}}, {'period':'all'},self.company)

    def test_other_company_excluded(self):
        other=self.env['res.company'].create({'name':'IP Empty Company'})
        result=self.provider.with_company(other)._run_source('finance.revenue',{'kind':'kpi','filters':{}},{'period':'all'},other)
        self.assertEqual(result['value'],0)

    def test_template_creates_and_loads_all_sources(self):
        boards=self.env['ip.dashboard'].with_company(self.company)
        board=boards.browse(boards.create_from_template('finance.executive'))
        data=board.fetch_data({'period':'custom','date_from':'2026-01-01','date_to':'2026-01-31'},self.company.id)
        self.assertEqual(len(data['results']),16)
        for metric in data['results'].values(): self.assertNotIn('error',metric)
