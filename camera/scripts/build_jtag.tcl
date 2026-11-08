set root [file normalize [file join [file dirname [info script]] ..]]
set output [file join $root build pds_jtag]
file mkdir $output
cd $output
set_arch -family Kosmo2 -device PG2K100 -speedgrade -6 -package MBG400
foreach path [lsort [glob [file join $root rtl *.v]]] { add_design $path }
foreach path [lsort [glob [file join $root jtag *.v]]] { add_design $path }
set iproot C:/pango/PDS_2025.2-ads/ip/system_ip/ips_dvio/ips_dvio_eval
foreach path [glob [file join $iproot ips_dvio rtl *.v] [file join $iproot ips_dvio_jtag_hub rtl *.v]] { add_design $path }
add_constraint [file join $root constraints camera.fdc]
add_constraint [file join $root constraints camera_jtag.fdc]
compile -top_module camera_jtag_top -verilog_standard Verilog_2001
synthesize -ads -selected_syn_tool_opt 2
dev_map
place
route
route_optimize
report_timing
source [file join $root scripts check_timing.tcl]
check_camera_timing [file join $output prj_tasks pnr_1 report_timing camera_jtag_top.rtr]
gen_netlist
gen_bit_stream
puts CAMERA_JTAG_BUILD_FINISHED
