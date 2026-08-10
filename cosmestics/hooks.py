app_name = "cosmestics"
app_title = "Cosmetics"
app_publisher = "Rono"
app_description = "ERPNext customizations for a cosmetics shop"
app_email = "ronoelisha625@gmail.com"
app_license = "mit"

# Apps
# ------------------

# Items, warehouses, suppliers and purchase documents all come from ERPNext.
required_apps = ["erpnext"]

# Installation
# ------------

# Creates the neighbour Supplier Group and POS settings defaults, then seeds the
# demo catalog only if the site has no items yet (see cosmestics/setup/demo.py).
after_install = "cosmestics.setup.install.after_install"

# Prerequisites only — never seeds data.
after_migrate = "cosmestics.setup.install.after_migrate"

# Each item in the list will be shown as an app in the apps page
# add_to_apps_screen = [
# 	{
# 		"name": "cosmestics",
# 		"logo": "/assets/cosmestics/logo.png",
# 		"title": "Cosmetics",
# 		"route": "/cosmestics",
# 		"has_permission": "cosmestics.api.permission.has_app_permission"
# 	}
# ]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/cosmestics/css/cosmestics.css"
# app_include_js = "/assets/cosmestics/js/cosmestics.js"

# include js, css files in header of web template
# web_include_css = "/assets/cosmestics/css/cosmestics.css"
# web_include_js = "/assets/cosmestics/js/cosmestics.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "cosmestics/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# The Cashiers table's Link field would otherwise offer every User on the site
# for a field that decides who may settle money against a till. Scopes it to the
# chosen POS Profile's applicable users.
doctype_js = {
	"POS Opening Entry": "public/js/pos_shift_cashiers.js",
	"POS Closing Entry": "public/js/pos_shift_cashiers.js",
}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "cosmestics/public/icons.svg"

# Website
# ----------

# Serve the POS SPA (and all its client-side routes) from cosmestics/www/pos.html
website_route_rules = [
	{"from_route": "/pos/<path:app_path>", "to_route": "pos"},
]

add_to_apps_screen = [
	{
		"name": "cosmestics",
		"logo": "/assets/cosmestics/images/logo.svg",
		"title": "POS",
		"route": "/pos",
	}
]

# Document Events
# ---------------

doc_events = {
	"Material Request": {
		# Posts the request to the staff WhatsApp group. Enqueued, best-effort:
		# a bridge outage must never block the request itself.
		"on_submit": "cosmestics.api.notifications.on_material_request_submit",
	},
}

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# automatically load and sync documents of this doctype from downstream apps
# importable_doctypes = [doctype_1]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "cosmestics.utils.jinja_methods",
# 	"filters": "cosmestics.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "cosmestics.install.before_install"
# after_install = "cosmestics.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "cosmestics.uninstall.before_uninstall"
# after_uninstall = "cosmestics.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "cosmestics.utils.before_app_install"
# after_app_install = "cosmestics.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "cosmestics.utils.before_app_uninstall"
# after_app_uninstall = "cosmestics.utils.after_app_uninstall"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "cosmestics.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# Document Events
# ---------------
# Hook on document methods and events

# doc_events = {
# 	"*": {
# 		"on_update": "method",
# 		"on_cancel": "method",
# 		"on_trash": "method"
# 	}
# }

# Scheduled Tasks
# ---------------

# scheduler_events = {
# 	"all": [
# 		"cosmestics.tasks.all"
# 	],
# 	"daily": [
# 		"cosmestics.tasks.daily"
# 	],
# 	"hourly": [
# 		"cosmestics.tasks.hourly"
# 	],
# 	"weekly": [
# 		"cosmestics.tasks.weekly"
# 	],
# 	"monthly": [
# 		"cosmestics.tasks.monthly"
# 	],
# }

# Testing
# -------

# before_tests = "cosmestics.install.before_tests"

# Extend DocType Class
# ------------------------------
#
# A till shift can have more than one cashier on it. ERPNext's two POS entries
# each assume it has exactly one — the closing entry refuses another cashier's
# invoices outright, which leaves a shared shift unclosable. These mixins widen
# the three checks that read the single `user` field to read the shift's roster
# instead; everything else ERPNext validates is untouched. See the modules.
extend_doctype_class = {
	"POS Opening Entry": "cosmestics.overrides.pos_opening_entry.SharedShiftOpeningMixin",
	"POS Closing Entry": "cosmestics.overrides.pos_closing_entry.SharedShiftClosingMixin",
}

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "cosmestics.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "cosmestics.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["cosmestics.utils.before_request"]
# after_request = ["cosmestics.utils.after_request"]

# Job Events
# ----------
# before_job = ["cosmestics.utils.before_job"]
# after_job = ["cosmestics.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"cosmestics.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
export_python_type_annotations = True

# Require all whitelisted methods to have type annotations
require_type_annotated_api_methods = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }

# Translation
# ------------
# List of apps whose translatable strings should be excluded from this app's translations.
# ignore_translatable_strings_from = []

