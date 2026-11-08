set root [file normalize [file join [file dirname [info script]] ..]]
set output [file join $root build pds]
file mkdir $output
cd $output
set_arch -family Kosmo2 -device PG2K100 -speedgrade -6 -package MBG400
foreach path [lsort [glob [file join $root rtl *.v]]] {add_design $path}
set iproot C:/pango/PDS_2025.2-ads/ip/system_ip/ips_dvio/ips_dvio_eval
foreach path [glob [file join $iproot ips_dvio rtl *.v] [file join $iproot ips_dvio_jtag_hub rtl *.v]] {add_design $path}
add_constraint [file join $root constraints board.fdc]
add_constraint [file join $root constraints ro_locations.fdc]
compile -top_module ro_puf_top -verilog_standard Verilog_2001
synthesize -ads -selected_syn_tool_opt 2
dev_map -devmap_remove_dups 0
place
route
route_optimize
report_timing
gen_netlist
gen_bit_stream
puts RO_PUF_BUILD_FINISHED
