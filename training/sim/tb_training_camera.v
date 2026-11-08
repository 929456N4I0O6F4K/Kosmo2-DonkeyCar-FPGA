`timescale 1ns/1ps
module tb_training_camera;
 reg clk=0,pclk=0,reset=1,ready=1,vsync=0,href=0;
 always #10 clk=~clk;always #21 pclk=~pclk;
 reg [7:0] data=0;
 reg [31:0] applied_sequence=7,applied_flags=3;
 reg signed [31:0] applied_angle=-250000,applied_throttle=120000;
 wire frame_valid,fault;reg frame_release=0;
 reg [15:0] frame_rd_addr=0;wire [7:0] frame_rd_data;
 wire [31:0] frame_sequence,frame_command_sequence,frame_flags,frame_dropped;
 wire signed [31:0] frame_angle,frame_throttle;
 wire [63:0] frame_ticks;
 integer x,y;reg [63:0] first_ticks;
 kosmo_training_camera #(.WIDTH(4),.HEIGHT(2),.CLOCK_HZ(10000)) dut(
 .clk(clk),.reset(reset),.camera_ready(ready),.pclk(pclk),.vsync(vsync),.href(href),.data(data),
 .applied_sequence(applied_sequence),.applied_flags(applied_flags),.applied_angle(applied_angle),.applied_throttle(applied_throttle),
 .frame_valid(frame_valid),.frame_release(frame_release),.frame_rd_addr(frame_rd_addr),.frame_rd_data(frame_rd_data),
 .frame_sequence(frame_sequence),.frame_command_sequence(frame_command_sequence),.frame_flags(frame_flags),.frame_dropped(frame_dropped),.frame_angle(frame_angle),.frame_throttle(frame_throttle),.frame_ticks(frame_ticks),.fault(fault));
 task send_frame(input integer rows);
  begin
   @(negedge pclk);vsync=1;repeat(5)@(negedge pclk);vsync=0;repeat(5)@(negedge pclk);
   // Change the current command after VSYNC. Completed frame keeps the old one.
   applied_sequence=8;applied_angle=300000;
   for(y=0;y<rows;y=y+1)begin
    for(x=0;x<8;x=x+1)begin href=1;data=y*8+x;@(negedge pclk);end
    href=0;repeat(5)@(negedge pclk);
   end
   vsync=1;repeat(5)@(negedge pclk);vsync=0;repeat(5)@(negedge pclk);
  end
 endtask
 initial begin
  repeat(5)@(negedge clk);reset=0;repeat(20)@(negedge pclk);
  send_frame(2);wait(frame_valid);
  if(frame_command_sequence!=7||frame_angle!=-250000||frame_throttle!=120000||frame_flags!=3||frame_sequence!=1)$fatal(1,"frame-start labels not frozen");
  first_ticks=frame_ticks;
  for(x=0;x<16;x=x+1)begin @(negedge clk);frame_rd_addr=x;@(posedge clk);#1;if(frame_rd_data!=x)$fatal(1,"capture data");end
  send_frame(2);if(frame_ticks!=first_ticks||frame_command_sequence!=7)$fatal(1,"held metadata overwritten");
  @(negedge clk);frame_release=1;@(negedge clk);frame_release=0;repeat(20)@(negedge pclk);
  send_frame(1);repeat(20)@(negedge pclk);if(frame_valid||frame_dropped!=1)$fatal(1,"malformed frame not discarded");
  send_frame(2);wait(frame_valid);if(frame_command_sequence!=8||frame_angle!=300000||frame_ticks<=first_ticks)$fatal(1,"next frame metadata");
  @(negedge clk);frame_release=1;@(negedge clk);frame_release=0;
  repeat(10100)@(negedge clk);if(!fault)$fatal(1,"capture timeout not latched");
  $display("ALL TRAINING CAMERA TESTS PASS");$finish;
 end
 initial begin #1000000;$fatal(1,"test timeout");end
endmodule
