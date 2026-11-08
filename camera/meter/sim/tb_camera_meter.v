`timescale 1ns/1ps
module tb_camera_meter;
 reg clk=0, resetn=0;
 always #10 clk=~clk;
 reg [31:0] control=0;
 tri scl,sda;
 reg pullups=1, external_scl_low=0;
 assign (pull1,highz0) scl=pullups ? 1'b1 : 1'bz;
 assign (pull1,highz0) sda=pullups ? 1'b1 : 1'bz;
 assign scl=external_scl_low ? 1'b0 : 1'bz;
 wire reset_out;
 wire [4:0] leds;
 wire [63:0] status;
 camera_meter_core #(.CLOCK_HZ(20),.INTERNAL_PULLUPS(1)) dut(.clk(clk),.resetn(resetn),.control(control),
  .cam_scl(scl),.cam_sda(sda),.cam_reset_n(reset_out),.led_n(leds),.status(status));
 task select_mode;
  input [7:0] tok,mode;
  begin @(negedge clk); control={16'h4d54,tok,mode}; repeat(8) @(negedge clk); end
 endtask
 initial begin
  #1;
  if(reset_out!==0 || scl!==1 || sda!==1) $fatal(1,"Reset must hold RST low and release SCCB");
  repeat(3) @(negedge clk); resetn=1; repeat(8) @(negedge clk);
  if(status[63:40]!==24'h4d5401 || reset_out!==1 || scl!==1 || sda!==1) $fatal(1,"Boot idle failed");
  if(status[16]!==1) $fatal(1,"Wrong pullup profile marker");
  select_mode(1,1);
  if(reset_out!==0 || scl!==1 || sda!==1) $fatal(1,"Sensor reset mode failed");
  select_mode(2,2);
  if(reset_out!==0 || scl!==0 || sda!==1 || status[2]!==0) $fatal(1,"SCL low mode failed");
  select_mode(3,3);
  if(reset_out!==0 || scl!==1 || sda!==0 || status[3]!==0) $fatal(1,"SDA low mode failed");
  select_mode(4,4);
  if(scl!==0 || sda!==0) $fatal(1,"Both low mode failed");
  select_mode(5,0);
  // An open-drain output must never drive high, even if external pullups are absent.
  pullups=0; repeat(4) @(negedge clk);
  if(scl!==1'bz || sda!==1'bz) $fatal(1,"Released bus actively driven");
  pullups=1; external_scl_low=1; repeat(6) @(negedge clk);
  if(status[2]!==0 || scl!==0 || status[4]!==0) $fatal(1,"External held-low line not detected");
  external_scl_low=0; repeat(6) @(negedge clk);
  if(status[2]!==1) $fatal(1,"Released SCL not detected");
  select_mode(5,4);
  if(status[39:32]!==0) $fatal(1,"Repeated token changed mode");
  select_mode(6,255);
  if(status[39:32]!==0 || status[7]!==1) $fatal(1,"Invalid command changed outputs");
  control=32'hca010704; repeat(8) @(negedge clk);
  if(status[39:32]!==0) $fatal(1,"Wrong magic accepted");
  select_mode(7,4); resetn=0; #1;
  if(reset_out!==0 || scl!==1 || sda!==1) $fatal(1,"Reset failed to release driven lines");
  $display("ALL CAMERA METER TESTS PASS: static modes, open drain, external fault, command guard, reset");
  $finish;
 end
 initial begin #100000; $fatal(1,"Simulation timeout"); end
endmodule
