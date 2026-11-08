`timescale 1ns/1ps
module tb_pca_esc;
 reg clk=0,resetn=0;
 always #500 clk=~clk;
 reg [31:0] control=0;
 reg present=1,hold_scl=0;
 tri1 scl,sda;
 wire [63:0] status,diagnostics;
 reg [7:0] token=0;
 integer i,old_writes;
 time first_neutral,first_target,last_neutral;
 pca_bench_core #(.CLOCK_HZ(1000000),.BUS_HZ(100000),.PULSE_CYCLES(30000),
  .RETRY_CYCLES(1000),.ESC_ARM_CYCLES(40000),.ESC_TEST_CYCLES(6000),.ESC_RETURN_CYCLES(15000)) dut(
  .clk(clk),.resetn(resetn),.control(control),.scl(scl),.sda(sda),.status(status),.diagnostics(diagnostics));
 pca9685_model chip(.present(present),.hold_scl(hold_scl),.hold_sda(1'b0),
  .bad_prescale(1'b0),.scl(scl),.sda(sda));
 task idle;
  begin wait(!status[2] && !status[3]); repeat(10) @(negedge clk); end
 endtask
 task send;
  input [3:0] op,ch;
  input [15:0] data;
  begin
   @(negedge clk); token=token+1'b1; control={token,op,ch,data};
   wait(status[39:32]==token); repeat(10) @(negedge clk);
  end
 endtask
 task all_off;
  begin
   for(i=0;i<16;i=i+1)
    if(chip.registers[9+4*i][4]!==1) $fatal(1,"ESC shutdown failed on %d",i);
  end
 endtask
 task only_esc;
  begin
   for(i=1;i<16;i=i+1)
    if(chip.registers[9+4*i][4]!==1) $fatal(1,"ESC command enabled another channel %d",i);
  end
 endtask
 task init_ok;
  begin send(2,0,0); idle; if(!status[0] || status[27:24]) $fatal(1,"Init failed"); end
 endtask
 task neutral_ok;
  begin
   send(5,0,307);
   wait(chip.registers[9]===1); first_neutral=$time;
   if(chip.registers[8]!==8'h33) $fatal(1,"Wrong neutral");
   only_esc;
   wait(status[4]); idle; all_off;
   if($time-first_neutral<40000000 || status[27:24]) $fatal(1,"Neutral did not hold complete interval");
  end
 endtask
 initial begin
  repeat(5) @(negedge clk); resetn=1; idle; all_off;
  init_ok; send(6,0,312); idle; all_off;
  if(status[27:24]!=4) $fatal(1,"Trial accepted before neutral sequence");
  init_ok; send(4,0,307); idle; all_off;
  if(status[27:24]!=3) $fatal(1,"Generic pulse bypassed ESC sequence");
  init_ok; send(5,3,307); idle; all_off;
  if(status[27:24]!=3) $fatal(1,"ESC command accepted wrong channel");
  init_ok; send(5,0,329); idle; all_off;
  if(status[27:24]!=3) $fatal(1,"Neutral range guard failed");
  init_ok; neutral_ok;
  // Off after successful completion must preserve the completed neutral test.
  send(1,0,0); idle;
  send(6,0,312);
  wait(chip.registers[9]===1); first_neutral=$time;
  if(chip.registers[8]!==8'h33) $fatal(1,"Trial did not start at neutral");
  only_esc;
  wait(chip.registers[8]===8'h38); first_target=$time;
  if(first_target-first_neutral<39000000 || first_target-first_neutral>42000000)
   $fatal(1,"Neutral dwell incorrect before throttle: %t",first_target-first_neutral);
  if(chip.registers[9]!==1) $fatal(1,"Signal gap at throttle transition");
  only_esc;
  wait(chip.registers[8]===8'h33); last_neutral=$time;
  if(last_neutral-first_target<5000000 || last_neutral-first_target>8000000)
   $fatal(1,"Throttle dwell incorrect: %t",last_neutral-first_target);
  if(chip.registers[9]!==1) $fatal(1,"Signal gap at neutral return");
  wait(chip.registers[9][4]);
  if($time-last_neutral<14000000 || $time-last_neutral>17000000)
   $fatal(1,"Return-to-neutral dwell incorrect");
  idle; all_off;
  if(!status[4] || status[1] || status[27:24]) $fatal(1,"Sequence completion not clean");
  old_writes=chip.writes; repeat(45000) @(negedge clk);
  if(chip.writes!=old_writes) $fatal(1,"Sequence replayed without new command");
  $display("PASS ESC neutral dwell, autonomous throttle/return/off timing, channel isolation, replay guard");

  send(6,0,312); wait(chip.registers[9]===1); idle;
  send(1,0,0); idle; all_off;
  repeat(45000) @(negedge clk); all_off;
  send(6,0,312); idle;
  if(status[27:24]!=4) $fatal(1,"Interrupted sequence retained neutral qualification");
  init_ok; neutral_ok;
  send(6,0,370); idle; all_off;
  if(status[27:24]!=3) $fatal(1,"Throttle upper bound ignored");
  init_ok; neutral_ok;
  send(6,0,255); idle; all_off;
  if(status[27:24]!=3) $fatal(1,"Throttle low byte rollover allowed");
  init_ok; neutral_ok;
  send(6,0,312); wait(chip.registers[8]===8'h38); hold_scl=1;
  wait(status[27:24]==2);
  if(!status[3] || !status[1] || status[0]) $fatal(1,"Fault falsely reported safe shutdown");
  hold_scl=0; idle; all_off;
  init_ok; send(6,0,312); idle;
  if(status[27:24]!=4) $fatal(1,"Fault/init did not revoke neutral qualification");
  $display("ALL PCA ESC TESTS PASS: off interrupt, qualification, range guards, wire fault and recovery");
  $finish;
 end
 initial begin #2000000000; $fatal(1,"ESC simulation timeout: %h phase %d step %d",status,dut.esc_phase,dut.step); end
endmodule
