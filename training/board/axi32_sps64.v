`timescale 1ns/1ps
`default_nettype none
// Aligned 8-byte transactions on a 64-bit SPS port, with 4-byte write strobes.
// Reads fetch both lanes, selecting the requested 32-bit word. One outstanding read
// and one outstanding write maximum, as guaranteed by KTR1 transport.
module axi32_sps64(
 input wire clk,reset,
 input wire [31:0] awaddr, input wire awvalid, output wire awready,
 input wire [31:0] wdata,input wire [3:0] wstrb,input wire wvalid,output wire wready,
 output wire [1:0] bresp,output wire bvalid,input wire bready,
 input wire [31:0] araddr,input wire arvalid,output wire arready,
 output wire [31:0] rdata,output wire [1:0] rresp,output wire rvalid,input wire rready,
 output wire [31:0] s_awaddr,output wire s_awvalid,input wire s_awready,
 output wire [63:0] s_wdata,output wire [7:0] s_wstrb,output wire s_wvalid,input wire s_wready,
 input wire [1:0] s_bresp,input wire s_bvalid,output wire s_bready,
 output wire [31:0] s_araddr,output wire s_arvalid,input wire s_arready,
 input wire [63:0] s_rdata,input wire [1:0] s_rresp,input wire s_rvalid,output wire s_rready
);
 reg write_lane,read_lane,have_aw;
 always @(posedge clk)begin
  if(reset)begin write_lane<=0;read_lane<=0;have_aw<=0;end
  else begin
   if(awvalid&&awready)begin write_lane<=awaddr[2];have_aw<=1;end
   if(wvalid&&wready)have_aw<=0;
   if(arvalid&&arready)read_lane<=araddr[2];
  end
 end
 assign s_awaddr={awaddr[31:3],3'd0};assign s_awvalid=awvalid;assign awready=s_awready;
 // Address is accepted first, so W may be delayed without losing lane select.
 assign s_wvalid=wvalid&&have_aw;assign wready=s_wready&&have_aw;
 assign s_wdata={wdata,wdata};assign s_wstrb=write_lane?{wstrb,4'd0}:{4'd0,wstrb};
 assign bresp=s_bresp;assign bvalid=s_bvalid;assign s_bready=bready;
 assign s_araddr={araddr[31:3],3'd0};assign s_arvalid=arvalid;assign arready=s_arready;
 assign rdata=read_lane?s_rdata[63:32]:s_rdata[31:0];
 assign rresp=s_rresp;assign rvalid=s_rvalid;assign s_rready=rready;
endmodule
`default_nettype wire
