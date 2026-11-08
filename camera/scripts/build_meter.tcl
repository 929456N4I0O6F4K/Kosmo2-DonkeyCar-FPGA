set root [file normalize [file join [file dirname [info script]] ..]]
set output [file join $root build pds_meter]
file mkdir $output
cd $output
set_arch -family Kosmo2 -device PG2K100 -speedgrade -6 -package MBG400
foreach path [lsort [glob [file join $root meter *.v]]] { add_design $path }
add_design [file join $root jtag camera_dvio.v]
set iproot C:/pango/PDS_2025.2-ads/ip/system_ip/ips_dvio/ips_dvio_eval
foreach path [glob [file join $iproot ips_dvio rtl *.v] [file join $iproot ips_dvio_jtag_hub rtl *.v]] { add_design $path }
add_constraint [file join $root constraints camera_meter.fdc]
compile -top_module camera_meter_top -verilog_standard Verilog_2001
synthesize -ads -selected_syn_tool_opt 2
dev_map
place
route
route_optimize
report_timing
set handle [open [file join $output prj_tasks pnr_1 report_timing camera_meter_top.rtr] r]
set report [read $handle]
close $handle
if {![regexp {Design Summary\s*:\s*All Constraints Met\.} $report] ||
    ![regexp {sysclk_50\s+20\.0000} $report] || ![regexp {jtag_tck\s+66\.6670} $report]} {
 error "Meter design timing or clock constraints failed"
}
gen_netlist
gen_bit_stream
puts CAMERA_METER_BUILD_FINISHED
