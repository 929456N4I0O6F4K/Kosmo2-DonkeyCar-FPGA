`default_nettype none
// Only two clock domains are needed, regardless of the number of ROs.
// The bank is stopped before these buses are sampled by the system clock.
(* syn_hier="hard" *)
module ro_counter #(parameter integer WIDTH=24)(input wire clock_in,clear,
 output reg [WIDTH-1:0] count=0,output reg overflow=0);
 (* syn_keep=1 *) wire [3:0] div;
 GTP_DFF_C div0(.CLK(clock_in),.D(~div[0]),.C(clear),.Q(div[0]));
 GTP_DFF_C div1(.CLK(div[0]),.D(~div[1]),.C(clear),.Q(div[1]));
 GTP_DFF_C div2(.CLK(div[1]),.D(~div[2]),.C(clear),.Q(div[2]));
 GTP_DFF_C div3(.CLK(div[2]),.D(~div[3]),.C(clear),.Q(div[3]));
 always @(posedge div[3] or posedge clear) begin
   if(clear) begin count<=0; overflow<=0; end
   else if(&count) overflow<=1;
   else count<=count+1'b1;
 end
endmodule
`default_nettype wire
