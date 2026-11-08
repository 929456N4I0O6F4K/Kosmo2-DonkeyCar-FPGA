# Run: pds_shell.exe -file scripts/build.tcl
set root [file normalize [file join [file dirname [info script]] ..]]
set output [file join $root build pds]
file mkdir $output
cd $output
set_arch -family Kosmo2 -device PG2K100 -speedgrade -6 -package MBG400
foreach path [lsort [glob [file join $root rtl *.v]]] { add_design $path }
add_constraint [file join $root constraints camera.fdc]
compile -top_module camera_top -verilog_standard Verilog_2001
synthesize -ads -selected_syn_tool_opt 2
dev_map
place
route
route_optimize
report_timing
source [file join $root scripts check_timing.tcl]
check_camera_timing [file join $output prj_tasks pnr_1 report_timing camera_top.rtr]
gen_netlist
gen_bit_stream
puts "CAMERA_BUILD_FINISHED: inspect timing and DRC reports before board testing"
