"""Desktop layer (Phase 30): tray, background mode, single-instance,
auto-start and the native-notification channel over the plan-24 funnel.

Everything here is desktop-only consumption: the web deployment never
imports this package (the shell entrypoint does), and every alert path
runs through EngagementService.emit — nothing creates its own alerts.
"""
