`timescale 1ns/1ps
module tb_axi32_sps64;
reg clk=0;always #10 clk=~clk;
reg reset=1;
reg [31:0] awaddr=0,wdata=0,araddr=0;
reg [3:0] wstrb=15;
reg awvalid=0,wvalid=0,bready=0,arvalid=0,rready=0;
wire awready,wready,bvalid,arready,rvalid;wire [31:0] rdata;
wire [1:0] bresp,rresp;
wire [31:0] s_awaddr,s_araddr;wire [63:0] s_wdata;wire [7:0] s_wstrb;
wire s_awvalid,s_wvalid,s_bready,s_arvalid,s_rready;
reg s_awready=0,s_wready=0,s_bvalid=0,s_arready=0,s_rvalid=0;
reg [1:0] s_bresp=0,s_rresp=0;
reg [63:0] s_rdata=64'h89abcdef01234567;
axi32_sps64 dut(.clk(clk),.reset(reset),
.awaddr(awaddr),.awvalid(awvalid),.awready(awready),.wdata(wdata),.wstrb(wstrb),.wvalid(wvalid),.wready(wready),.bresp(bresp),.bvalid(bvalid),.bready(bready),
.araddr(araddr),.arvalid(arvalid),.arready(arready),.rdata(rdata),.rresp(rresp),.rvalid(rvalid),.rready(rready),
.s_awaddr(s_awaddr),.s_awvalid(s_awvalid),.s_awready(s_awready),.s_wdata(s_wdata),.s_wstrb(s_wstrb),.s_wvalid(s_wvalid),.s_wready(s_wready),.s_bresp(s_bresp),.s_bvalid(s_bvalid),.s_bready(s_bready),
.s_araddr(s_araddr),.s_arvalid(s_arvalid),.s_arready(s_arready),.s_rdata(s_rdata),.s_rresp(s_rresp),.s_rvalid(s_rvalid),.s_rready(s_rready));
task tick;begin @(posedge clk);#1;end endtask
task write_test;
input [31:0] addr;input [7:0] expected;
begin
 @(negedge clk);awaddr=addr;wdata=32'hdeadbeef;awvalid=1;wvalid=1;s_wready=1;
 repeat(3)begin tick;if(wready||s_wvalid)$fatal(1,"W accepted before AW");if(s_awaddr!={addr[31:3],3'b0})$fatal(1,"AW alignment");end
 @(negedge clk);s_awready=1;tick;
 if(!s_wvalid||s_wstrb!=expected||s_wdata!=64'hdeadbeefdeadbeef)$fatal(1,"lane/strobe mismatch");
 @(negedge clk);awvalid=0;s_awready=0;s_wready=0;
 repeat(3)begin tick;if(!s_wvalid||s_wstrb!=expected)$fatal(1,"W changed under backpressure");end
 @(negedge clk);s_wready=1;tick;
 @(negedge clk);wvalid=0;s_bvalid=1;s_bresp=2;bready=1;#1;
 if(!bvalid||bresp!=2||!s_bready)$fatal(1,"B response");
 tick;@(negedge clk);s_bvalid=0;bready=0;
end endtask
task read_test;
input [31:0] addr,expected;
begin
 @(negedge clk);araddr=addr;arvalid=1;s_arready=1;#1;
 if(s_araddr!={addr[31:3],3'b0})$fatal(1,"AR alignment");tick;
 @(negedge clk);arvalid=0;s_arready=0;araddr=~addr;s_rvalid=1;s_rresp=2;
 repeat(3)begin tick;if(!rvalid||rdata!=expected||rresp!=2)$fatal(1,"R lane/hold mismatch");end
 @(negedge clk);rready=1;#1;if(!s_rready)$fatal(1,"R ready");tick;
 @(negedge clk);s_rvalid=0;rready=0;
end endtask
initial begin
 repeat(3)tick;reset=0;
 write_test('h300000,8'h0f);write_test('h300004,8'hf0);
 wstrb=4'b0101;write_test('h30000c,8'h50);
 read_test('h300000,32'h01234567);read_test('h300004,32'h89abcdef);
 $display("ALL AXI WIDTH ADAPTER TESTS PASS");$finish;
end
initial begin #100000;$fatal(1,"timeout");end
endmodule
