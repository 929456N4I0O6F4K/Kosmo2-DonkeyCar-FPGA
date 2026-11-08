set root [file normalize [file join [file dirname [info script]] ..]]
set output [file join $root build board]
file mkdir $output
if {[string tolower [file normalize [pwd]]] ne [string tolower $output]} {
 error "Start PDS from $output; PDS creates tasks in its launch directory before this script runs."
}
cd $output
set_arch -family Kosmo2 -device PG2K100 -speedgrade -6 -package MBG400
foreach path [glob [file join $root rtl *.v] [file join $root board *.v] [file join $root board vendor *.v]] { add_design $path }
foreach name {camera_capture camera_config camera_sccb camera_exposure ov2640_init_rom} {add_design [file join $root .. camera rtl $name.v]}
foreach name {pca_i2c pca_dvio} {add_design [file join $root .. actuators rtl $name.v]}
set iproot C:/pango/PDS_2025.2-ads/ip/system_ip/ips_dvio/ips_dvio_eval
foreach path [glob [file join $iproot ips_dvio rtl *.v] [file join $iproot ips_dvio_jtag_hub rtl *.v]] {add_design $path}
add_constraint [file join $root board training.fdc]
compile -top_module kosmo_training_top -verilog_standard Verilog_2001
synthesize -ads -selected_syn_tool_opt 2
dev_map
place
route
route_optimize
report_timing
set f [open [file join $output prj_tasks pnr_1 report_timing kosmo_training_top.rtr] r]
set report [read $f]
close $f
if {![regexp {Design Summary\s*:\s*All Constraints Met\.} $report]} {error "Training board timing failed"}
gen_netlist
gen_bit_stream
puts TRAINING_BOARD_BUILD_FINISHED
