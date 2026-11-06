from odoo import api, fields, models, _
from odoo.exceptions import AccessError, ValidationError
from .finance_math import INCOME, EXPENSE, ASSET, LIABILITY, EQUITY, totals, age_bucket

# Every query is company-scoped, posted only and performed with the viewer's rights.
GROUPS = ['account.group_account_readonly', 'account.group_account_user', 'account.group_account_manager']
METRICS = {
    'revenue': ('Revenue', 'الإيرادات', 'period', INCOME, -1),
    'cogs': ('Cost of revenue', 'تكلفة الإيرادات', 'period', ('expense_direct_cost',), 1),
    'expenses': ('Operating expenses', 'المصروفات التشغيلية', 'period', ('expense', 'expense_depreciation'), 1),
    'gross_profit': ('Gross profit', 'إجمالي الربح', 'period', (), 1),
    'net_profit': ('Net profit', 'صافي الربح', 'period', (), 1),
    'net_margin': ('Net profit margin', 'هامش صافي الربح', 'period', (), 1),
    'pnl': ('Profit and loss summary', 'ملخص الأرباح والخسائر', 'period', (), 1),
    'cash': ('Cash and bank balance', 'رصيد النقد والبنوك', 'closing', ('asset_cash',), 1),
    'cash_movement': ('Net cash account movement', 'صافي حركة الحسابات النقدية', 'period', ('asset_cash',), 1),
    'assets': ('Total assets', 'إجمالي الأصول', 'closing', ASSET, 1),
    'liabilities': ('Total liabilities', 'إجمالي الالتزامات', 'closing', LIABILITY, -1),
    'equity_earnings': ('Equity including unclosed earnings', 'حقوق الملكية مع الأرباح غير المقفلة', 'closing', (), 1),
    'balance_sheet': ('Balance sheet summary', 'ملخص الميزانية العمومية', 'closing', (), 1),
    'receivable': ('Current net receivables', 'صافي الحسابات المدينة الحالي', 'current', ('asset_receivable',), 1),
    'payable': ('Current net payables', 'صافي الحسابات الدائنة الحالي', 'current', ('liability_payable',), -1),
    'overdue_receivable': ('Current overdue receivables', 'الحسابات المدينة المتأخرة حالياً', 'current', ('asset_receivable',), 1),
    'overdue_payable': ('Current overdue payables', 'الحسابات الدائنة المتأخرة حالياً', 'current', ('liability_payable',), -1),
    'aged_receivable': ('Current aged receivable', 'أعمار الديون المدينة الحالية', 'current', ('asset_receivable',), 1),
    'aged_payable': ('Current aged payable', 'أعمار الديون الدائنة الحالية', 'current', ('liability_payable',), -1),
}
GROUP_FILTER = {'key': 'group_by', 'label': 'Breakdown', 'label_ar': 'التجميع حسب',
    'options': [['account', 'Account', 'الحساب'], ['partner', 'Contact', 'جهة الاتصال'],
                ['journal', 'Journal', 'دفتر اليومية'], ['month', 'Month', 'الشهر']],
    'domains': {'account': [], 'partner': [], 'journal': [], 'month': []}}

class FinanceProvider(models.AbstractModel):
    _inherit = 'ip.dashboard.provider'

    @api.model
    def _get_sources(self):
        result = dict(super()._get_sources())
        for key, (en, ar, mode, types, sign) in METRICS.items():
            grouped = bool(types) and not key.startswith('aged_')
            result['finance.'+key] = {
                'label': en, 'label_ar': ar, 'module': 'Finance', 'groups': GROUPS,
                'model': 'account.move.line', 'company_field': 'company_id',
                'kinds': ['kpi'] if key in ('gross_profit', 'net_profit', 'net_margin', 'equity_earnings') else
                         ['table', 'bar'] if key in ('pnl', 'balance_sheet', 'aged_receivable', 'aged_payable') else ['kpi', 'bar', 'table'],
                'filters': [GROUP_FILTER] if grouped else [],
            }
        return result

    def _run_source(self, source_key, block, filters, company):
        if not source_key.startswith('finance.'):
            return super()._run_source(source_key, block, filters, company)
        spec = self._get_sources().get(source_key)
        if not spec or not self._source_allowed(spec):
            raise AccessError(_('This financial source is unavailable.'))
        if block['kind'] not in spec['kinds']:
            raise ValidationError(_('Unsupported visualization for this financial source.'))
        # Reuse the core's strict filter validation, even for specialist sources.
        domain = self._get_domain(spec, block.get('filters', {}), filters, company)
        start, end = self._period_bounds(filters)
        today = fields.Date.context_today(self)
        end = end or today
        key = source_key.split('.', 1)[1]
        en, ar, mode, types, sign = METRICS[key]
        domain += [('parent_state', '=', 'posted')]
        model = self.env['account.move.line'].with_company(company).with_context(allowed_company_ids=[company.id])
        model.check_access('read')
        if mode == 'current':
            domain += [('date', '<=', today), ('amount_residual', '!=', 0)]
        else:
            domain += [('date', '<=', end)]
            if mode == 'period' and start:
                domain += [('date', '>=', start)]
        if types:
            domain += [('account_id.account_type', 'in', list(types))]
        if key.startswith('overdue_'):
            domain += ['|', ('date_maturity', '<', today), '&', ('date_maturity', '=', False), ('date', '<', today)]
        arabic = (self.env.context.get('lang') or '').startswith('ar')
        result = dict(value=0.0, unit='percent' if key == 'net_margin' else 'currency',
                      currency=company.currency_id.name, rows=[], truncated=False,
                      group_label='Account', group_label_ar='الحساب')
        scope = ('Current outstanding as of %s; period filter does not apply.' % today if mode == 'current' else
                 'Closing balances through %s.' % end if mode == 'closing' else
                 'Posted activity: %s to %s.' % (start or 'inception', end))
        scope_ar = ('المتبقي الحالي بتاريخ %s؛ لا ينطبق مرشح الفترة.' % today if mode == 'current' else
                    'الأرصدة الختامية حتى %s.' % end if mode == 'closing' else
                    'الحركات المرحلة: %s إلى %s.' % (start or 'البداية', end))
        unit_label = '%' if key == 'net_margin' else company.currency_id.name
        result.update(scope=scope+' '+unit_label, scope_ar=scope_ar+' '+unit_label)
        aggregate = 'amount_residual:sum' if mode == 'current' else 'balance:sum'
        if key.startswith('aged_'):
            buckets = [0.0]*5
            # Aggregate by dates, not individual records: respects rules without loading all lines.
            for due, booked, amount in model._read_group(domain, ['date_maturity:day', 'date:day'], [aggregate]):
                due = fields.Date.to_date(due or booked)
                buckets[age_bucket(due, today)] += sign*(amount or 0.0)
            labels = ['Not due', '1–30 days', '31–60 days', '61–90 days', 'Over 90 days']
            labels_ar = ['غير مستحق', '١–٣٠ يوم', '٣١–٦٠ يوم', '٦١–٩٠ يوم', 'أكثر من ٩٠ يوم']
            result.update(value=sum(buckets), group_label='Age (today)', group_label_ar='العمر (اليوم)',
                rows=[{'label': (labels_ar if arabic else labels)[i], 'value': v} for i, v in enumerate(buckets)])
            return result
        if not types:
            grouped = model._read_group(domain, ['account_id'], ['balance:sum'])
            by_type = {}
            for account, value in grouped:
                by_type[account.account_type] = by_type.get(account.account_type, 0.0)+(value or 0.0)
            values = totals(by_type)
            if key in ('pnl', 'balance_sheet'):
                keys = ['revenue', 'cogs', 'gross_profit', 'expenses', 'net_profit'] if key == 'pnl' else ['assets', 'liabilities', 'equity_earnings']
                result['rows'] = [{'label': METRICS[k][1 if arabic else 0], 'value': values[k]} for k in keys]
                result['value'] = values['net_profit'] if key == 'pnl' else values['assets']
                result.update(group_label='Report line', group_label_ar='بند التقرير')
            else:
                result['value'] = values[key]
            return result
        result['value'] = sign*(model._read_group(domain, aggregates=[aggregate])[0][0] or 0.0)
        if block['kind'] == 'kpi':
            return result
        grouping = block.get('filters', {}).get('group_by', 'account')
        field, label, label_ar = {
            'account': ('account_id', 'Account', 'الحساب'),
            'partner': ('partner_id', 'Contact', 'جهة الاتصال'),
            'journal': ('journal_id', 'Journal', 'دفتر اليومية'),
            'month': ('date:month', 'Posting month', 'شهر الترحيل'),
        }[grouping]
        groups = model._read_group(domain, [field], [aggregate])
        if grouping == 'month':
            groups.sort(key=lambda row: row[0])
            # Latest twelve chronological months; total still covers the full period.
            selected = groups[-12:]
        else:
            selected = sorted(groups, key=lambda row: abs(row[1] or 0), reverse=True)[:12]
        result.update(truncated=len(groups)>12, group_label=label, group_label_ar=label_ar)
        for group, amount in selected:
            label = group.display_name if isinstance(group, models.BaseModel) and group else ''
            if grouping == 'month':
                label = fields.Date.to_date(group).strftime('%Y-%m')
            result['rows'].append({'label': label, 'value': sign*(amount or 0.0)})
        return result

    @api.model
    def _get_templates(self):
        def block(key, kind='kpi', width=1, grouping=None):
            en, ar, mode, _, _ = METRICS[key]
            notes = {
                'period': ('Posted activity in the selected period; company currency.', 'الحركات المرحلة خلال الفترة المحددة؛ بعملة الشركة.'),
                'closing': ('Posted balances through the period end, including opening history.', 'الأرصدة المرحلة حتى نهاية الفترة، بما فيها الأرصدة الافتتاحية.'),
                'current': ('Outstanding TODAY, net of credits; ignores the period filter. Not historical aging.', 'المتبقي اليوم بعد الأرصدة المقابلة؛ لا يتبع مرشح الفترة. ليس تقرير أعمار تاريخياً.'),
            }
            note, note_ar = notes[mode]
            if key == 'net_margin':
                note += ' Zero when revenue is zero.'
                note_ar += ' صفر عند انعدام الإيرادات.'
            if key == 'cash_movement':
                note += ' Not a classified cash flow statement.'
                note_ar += ' ليست قائمة تدفقات نقدية مصنفة.'
            if grouping == 'month':
                note += ' Last 12 months with entries shown.'
                note_ar += ' آخر 12 شهراً لها حركات.'
            return dict(id=key+'_'+kind, source='finance.'+key, kind=kind, width=width,
                        title=en, title_ar=ar, note=note, note_ar=note_ar,
                        filters={'group_by': grouping} if grouping else {})
        return super()._get_templates() + [
            dict(key='finance.executive', name='Finance — Executive overview', name_ar='المالية — نظرة تنفيذية',
                 description='Posted performance, balances and current collection priorities.',
                 description_ar='الأداء المرحل والأرصدة وأولويات التحصيل الحالية.', blocks=[
                     block('revenue'), block('net_profit'), block('net_margin'), block('cash'),
                     block('receivable'), block('payable'), block('overdue_receivable'), block('overdue_payable'),
                     block('revenue', 'bar', 2, 'month'), block('expenses', 'bar', 2, 'account'),
                     block('pnl', 'table', 2), block('balance_sheet', 'table', 2),
                     block('aged_receivable', 'bar', 2), block('aged_payable', 'bar', 2),
                     block('overdue_receivable', 'table', 2, 'partner'), block('overdue_payable', 'table', 2, 'partner')]),
            dict(key='finance.performance', name='Finance — Profit and loss', name_ar='المالية — الأرباح والخسائر',
                 description='Revenue, costs, margins and account breakdowns.', description_ar='الإيرادات والتكاليف والهوامش وتفاصيل الحسابات.', blocks=[
                     block('revenue'), block('cogs'), block('gross_profit'), block('expenses'),
                     block('net_profit'), block('net_margin'), block('cash_movement', 'kpi', 2),
                     block('pnl', 'table', 4), block('revenue', 'bar', 2, 'month'), block('expenses', 'bar', 2, 'month'),
                     block('revenue', 'table', 2, 'account'), block('expenses', 'table', 2, 'account')]),
            dict(key='finance.collections', name='Finance — Receivables and payables', name_ar='المالية — الحسابات المدينة والدائنة',
                 description='Current open balances and aging, net of credits; independent of the period filter.',
                 description_ar='الأرصدة المفتوحة وأعمار الديون الحالية بعد الأرصدة المقابلة؛ مستقلة عن مرشح الفترة.', blocks=[
                     block('receivable'), block('payable'), block('overdue_receivable'), block('overdue_payable'),
                     block('aged_receivable', 'table', 2), block('aged_payable', 'table', 2),
                     block('receivable', 'table', 2, 'partner'), block('payable', 'table', 2, 'partner')]),
        ]
