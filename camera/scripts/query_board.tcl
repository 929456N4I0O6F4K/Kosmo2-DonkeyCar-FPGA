# Read-only JTAG identification. No configuration or flash writes.
cfg_set_tcl_break -flag true
cfg_connect -ip 127.0.0.1 -port 65420
cfg_scan_chain
# Kosmo2 chain order: index 0 is PU (ARM DAP), index 1 is PG2K100 PA.
cfg_read_device_property -mode 0 -device_index 1
cfg_read_device_property -mode 3 -device_index 1
cfg_disconnect
cfg_close
