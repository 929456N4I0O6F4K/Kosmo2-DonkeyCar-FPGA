`timescale 1ns/1ps
module tb_camera_exposure;
 reg clk=0;always #10 clk=~clk;
 reg reset=1,valid=0,present=1;
 reg [31:0] setting=0;
 tri1 scl,sda;
 wire ready,failed,done;wire [1:0] status;wire [31:0] applied;
 camera_config #(.CLOCK_HZ(100000),.BUS_HZ(10000),.SCL_PUSH_PULL(1),.RUNTIME_EXPOSURE(1)) dut(
  .clk(clk),.rst(reset),.colorbar(1'b0),.cam_reset_n(),.ready(ready),.failed(failed),
  .id_ok(),.pid(),.ver(),.error_code(),.config_index(),.scl(scl),.sda(sda),.debug_sccb(),
  .exposure_valid(valid),.exposure_setting(setting),.exposure_done(done),.exposure_status(status),.exposure_applied(applied));
 ov2640_model sensor(.present(present),.bad_id(1'b0),.hold_scl(1'b0),.scl(scl),.sda(sda));
 task request;
  input [31:0] value;
  input [1:0] expected;
  begin
   @(negedge clk);setting=value;valid=1;
   wait(done);#1;if(status!=expected)$fatal(1,"exposure status got %d wanted %d",status,expected);
   if(expected==1&&applied!=value)$fatal(1,"applied setting mismatch");
   repeat(5)@(negedge clk);
   if(done)$fatal(1,"duplicate completion while valid held");
   valid=0;repeat(8)@(negedge clk);
  end
 endtask
 task check_manual;
  input integer value;
  begin
   request(value,1);
   if(sensor.registers['h113]&5)$fatal(1,"AEC/AGC not disabled");
   if(sensor.registers['h104]!=(8'hac|(value&3)))$fatal(1,"orientation bits corrupted");
   if(sensor.registers['h110]!=((value>>2)&255))$fatal(1,"AEC high bits mismatch");
   if(sensor.registers['h145]!=(8'hc0|(value>>10)))$fatal(1,"REG45 preserved bits corrupted");
   if(sensor.registers['hc2]!=8'hce)$fatal(1,"DSP pixel format changed");
   if(sensor.registers['h100]!=8'h35)$fatal(1,"gain value overwritten");
  end
 endtask
 initial begin
  repeat(5)@(negedge clk);reset=0;wait(ready);if(failed)$fatal(1,"initialization failed");
  sensor.registers['h104]=8'hac;sensor.registers['h145]=8'hc0;
  sensor.registers['h100]=8'h35;sensor.registers['hc2]=8'h8e;
  check_manual(0);check_manual(300);check_manual(1200);
  request(32'h8000012c,1);
  if((sensor.registers['h113]&5)!=5||sensor.registers['hc2]!=8'h8e)$fatal(1,"auto AEC/AGC/DSP not restored");
  request(1201,2);request(32'h00001000,2);
  if(failed)$fatal(1,"invalid settings incorrectly faulted camera");
  present=0;request(300,3);repeat(5)@(negedge clk);
  if(!failed)$fatal(1,"SCCB error did not latch camera failure");
  present=1;reset=1;repeat(5)@(negedge clk);reset=0;wait(ready);
  // Corrupt readback only after writes: completion must fail, never claim applied.
  @(negedge clk);setting=300;valid=1;
  wait(dut.runtime_control.exposure.step==8);force dut.read_data=8'h00;
  wait(done);#1;if(status!=3)$fatal(1,"register readback mismatch accepted");
  release dut.read_data;
  $display("ALL CAMERA EXPOSURE TESTS PASS: manual extremes, auto restore, masks, gain hold, invalid inputs, NACK, readback failure");$finish;
 end
 initial begin #200000000;$fatal(1,"exposure test timeout");end
endmodule
