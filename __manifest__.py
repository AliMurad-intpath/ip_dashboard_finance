{
    'name': 'IP Dashboard — Finance',
    'summary': 'Executive finance, profit and loss, balances and collections for IP Dashboard',
    'version': '19.0.1.0.0',
    'category': 'Accounting/Accounting',
    'author': 'Integrated Path for IT Solutions',
    'license': 'LGPL-3',
    'depends': ['ip_dashboard', 'account'],
    'assets': {'web.assets_backend': ['ip_dashboard_finance/static/src/xml/finance.xml']},
    'application': False,
    'installable': True,
}
