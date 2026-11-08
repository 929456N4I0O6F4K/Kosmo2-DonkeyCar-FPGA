`timescale 1ns/1ps
module tb_camera_jtag_bridge;
 wire narrow_done,wide_done;
 camera_jtag_bridge_case #(.PAGE_SHIFT(5)) narrow(.finished(narrow_done));
 camera_jtag_bridge_case #(.PAGE_SHIFT(8)) wide(.finished(wide_done));
 initial begin
  wait(narrow_done && wide_done);
  $display("ALL CAMERA JTAG BRIDGE TESTS PASS: 32/256-byte pages, full packets, token, reset, bounds");
  $finish;
 end
 initial begin #20000000; $fatal(1,"timeout"); end
endmodule

module camera_jtag_bridge_case #(parameter integer PAGE_SHIFT=5)(output reg finished=0);
 localparam integer PAGE_BYTES=1<<PAGE_SHIFT, READ_CYCLES=PAGE_BYTES*2+10;
 reg clk=0,rst=1,idle=1,packet_valid=0;
 reg [31:0] control=0;
 reg [7:0] packet_data=0;
 wire [7:0] command_data;
 wire command_valid;
 wire [63:0] status;
 wire [PAGE_BYTES*8-1:0] page_data;
 integer i,j,p,seen=0;
 camera_jtag_bridge #(.PAGE_SHIFT(PAGE_SHIFT)) dut(.clk(clk),.rst(rst),.control(control),.idle(idle),
  .packet_valid(packet_valid),.packet_data(packet_data),.command_valid(command_valid),
  .command_data(command_data),.status(status),.page_data(page_data));
 always #10 clk=~clk;
 always @(posedge clk) if (command_valid) seen=seen+1;
 task send_packet;
  input integer count;
  begin
   wait(command_valid); @(negedge clk); idle=0;
   for (i=0;i<count;i=i+1) begin
    packet_data=(i*7+13)&255; packet_valid=1;
    @(negedge clk); packet_valid=0;
    @(negedge clk);
   end
   idle=1;
   wait(status[10]);
   repeat(READ_CYCLES) @(negedge clk);
  end
 endtask
 initial begin
  repeat(5) @(negedge clk); rst=0;
  control=32'h00000146;
  send_packet(38444);
  if (status[31:16]!=38444 || status[7:0]!=1 || !status[12] || status[11]) $fatal(1,"full packet status");
  if(status[63:48]!=(PAGE_SHIFT==5 ? 16'hca01 : 16'hca02)) $fatal(1,"signature");
  for(p=0;p<(38444+PAGE_BYTES-1)/PAGE_BYTES;p=p+1) begin
   control[31:16]=p;
   repeat(READ_CYCLES) @(negedge clk);
   if (!status[12] || status[47:32]!=p) $fatal(1,"page ack");
   for(j=0;j<PAGE_BYTES;j=j+1) begin
    if (p*PAGE_BYTES+j<38444) begin
     if(page_data[j*8 +: 8]!==(((p*PAGE_BYTES+j)*7+13)&255)) $fatal(1,"page byte mismatch %d",p*PAGE_BYTES+j);
    end else if(page_data[j*8 +: 8]!==0) $fatal(1,"last page padding not zero");
   end
  end
  if(seen!=1) $fatal(1,"page read replayed command");
  control[31:16]=16'hffff;
  repeat(READ_CYCLES) @(negedge clk);
  if(page_data!==0) $fatal(1,"out of range page not zero");
  control=32'h00000253; send_packet(44);
  if(status[31:16]!=44 || status[7:0]!=2 || page_data[7:0]!=13) $fatal(1,"second packet did not replace first");
  control=32'h00000346; send_packet(38445);
  if(!status[11] || status[31:16]!=38444) $fatal(1,"overflow not bounded");
  rst=1; @(negedge clk); control=0; rst=0;
  repeat(5) @(negedge clk);
  if(status[10] || status[7:0]!=0) $fatal(1,"reset did not clear handshake");
  $display("PASS JTAG bridge: %d bytes/page",PAGE_BYTES);
  finished=1;
 end
endmodule
