# Volatile PA configuration; replaces camera logic until it is reloaded.
set root [file normalize [file join [file dirname [info script]] ..]]
set bitstream [file join $root build pds prj_tasks pnr_1 generate_bitstream pca_bench_top.sbit]
if {![file exists $bitstream]} { error "PCA bench bitstream missing: $bitstream" }
cfg_set_tcl_break -flag true
cfg_connect -ip 127.0.0.1 -port 65420
cfg_scan_chain
cfg_read_device_property -mode 0 -device_index 1
cfg_assign_file -file $bitstream -device_index 1
cfg_program -device_index 1
cfg_read_device_property -mode 3 -device_index 1
cfg_disconnect
cfg_close
