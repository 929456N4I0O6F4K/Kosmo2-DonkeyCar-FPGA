`default_nettype none
(* syn_hier="hard" *)
module ro_bank(input wire enable,input wire [4:0] select_a,select_b,
 output wire clock_a,clock_b);
 (* syn_keep=1 *) wire [63:0] clocks;
 genvar i;
 generate for(i=0;i<64;i=i+1) begin: osc
   wire selected = i<32 ? select_a==i : select_b==i-32;
   ro_cell ro_unit(.enable(enable & selected),.clock_out(clocks[i]));
 end endgenerate
 assign clock_a=clocks[select_a];
 assign clock_b=clocks[{1'b1,select_b}];
endmodule
`default_nettype wire
