`timescale 1ns/1ps
module tb_pca_bench;
 reg clk=0,resetn=0;
 always #500 clk=~clk;
 reg [31:0] control=0;
 reg present=1,hold_scl=0,hold_sda=0,bad_prescale=0;
 tri1 scl,sda;
 wire [63:0] status,diagnostics;
 reg [7:0] token=0;
 integer i,old_writes;
 pca_bench_core #(.CLOCK_HZ(1000000),.BUS_HZ(100000),
  .PULSE_CYCLES(30000),.RETRY_CYCLES(1000)) dut(
  .clk(clk),.resetn(resetn),.control(control),.scl(scl),.sda(sda),.status(status),.diagnostics(diagnostics));
 pca9685_model chip(.present(present),.hold_scl(hold_scl),.hold_sda(hold_sda),
  .bad_prescale(bad_prescale),.scl(scl),.sda(sda));
 task settle;
  begin wait(!status[2] && !status[3]); repeat(10) @(negedge clk); end
 endtask
 task command;
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
    if(chip.registers[9+4*i][4]!==1) $fatal(1,"Channel %d not off",i);
  end
 endtask
 task init_ok;
  begin
   command(2,0,0); settle;
   if(!status[0] || status[27:24]!=0) $fatal(1,"Init not ready: %h",status);
   if(chip.registers[0]!==0 || chip.registers[1]!==4 || chip.registers[254]!==121)
    $fatal(1,"50 Hz configuration incorrect");
   all_off;
  end
 endtask
 task pulse7;
  begin
   command(4,7,307); wait(status[1]); settle;
   if(chip.registers[34]!==0 || chip.registers[35]!==0 ||
      chip.registers[36]!==8'h33 || chip.registers[37]!==1)
    $fatal(1,"1500 us pulse register values incorrect");
   for(i=0;i<16;i=i+1)
    if(i!=7 && chip.registers[9+4*i][4]!==1) $fatal(1,"Wrong channel enabled");
  end
 endtask
 initial begin
  repeat(5) @(negedge clk); resetn=1; settle; all_off;
  if(status[0] || status[1]) $fatal(1,"Boot unexpectedly armed");
  command(4,7,307); settle; all_off;
  if(status[27:24]!=4) $fatal(1,"Uninitialized pulse accepted");
  init_ok;
  command(3,0,254); settle;
  if(status[23:16]!==121) $fatal(1,"Register read failed");
  command(4,7,245); settle; all_off;
  if(status[27:24]!=3) $fatal(1,"Out of range pulse accepted");
  init_ok; pulse7;
  wait(status[4]); settle; all_off;
  if(status[1]) $fatal(1,"Timeout left active flag");
  old_writes=chip.writes;
  repeat(40000) @(negedge clk);
  if(chip.writes!=old_writes) $fatal(1,"Repeated token retriggered pulse");
  $display("PASS startup off, configuration, readback, bounds, single channel, expiry and replay guard");
  pulse7; command(1,0,0); settle; all_off;
  pulse7; command(4,7,307); settle; all_off;
  if(status[27:24]!=3) $fatal(1,"Pulse duration extended by new token");
  init_ok; pulse7;
  @(negedge clk); resetn=0; control=0; token=0;
  repeat(5) @(negedge clk); resetn=1; settle; all_off;
  if(status[0]) $fatal(1,"Reset retained ready state");
  $display("PASS explicit off, retrigger rejection and PA reset with PCA still powered");
  present=0; command(2,0,0);
  wait(status[27:24]==1); repeat(10) @(negedge clk);
  if(status[0] || !status[3]) $fatal(1,"NACK must inhibit outputs and report pending shutdown");
  present=1; settle; all_off;
  init_ok; pulse7; hold_scl=1;
  wait(status[27:24]==2);
  if(!status[3] || status[0]) $fatal(1,"Stuck clock fault not retained");
  // A broken bus cannot guarantee stop: report active/unknown until recovery.
  if(!status[1] || chip.registers[37][4]) $fatal(1,"Fault falsely claimed shutdown");
  hold_scl=0; settle; all_off;
  if(status[1]) $fatal(1,"Failed to shut down after wire recovery");
  command(4,7,307); settle; all_off;
  if(status[27:24]!=4) $fatal(1,"Fault recovery automatically rearmed");
  hold_sda=1; command(2,0,0); wait(status[27:24]==2);
  hold_sda=0; settle; all_off;
  bad_prescale=1; command(2,0,0); wait(status[27:24]==5);
  bad_prescale=0; settle; all_off;
  if(status[0]) $fatal(1,"Bad configuration readback accepted");
  init_ok;
  command(4,3,400); wait(status[1]); settle;
  if(chip.registers[20]!==8'h90 || chip.registers[21]!==1) $fatal(1,"Extended steering pulse failed");
  wait(status[4]); settle; all_off;
  command(4,3,531); settle; all_off;
  if(status[27:24]!=3) $fatal(1,"Steering upper bound not enforced");
  init_ok; command(4,0,400); settle; all_off;
  if(status[27:24]!=3) $fatal(1,"Steering extension leaked into throttle channel");
  init_ok;
  $display("PASS extended range confined to steering channel 3, upper bound enforced");
  $display("ALL PCA BENCH TESTS PASS: NACK, stuck SCL/SDA, shutdown retry, fault rearm guard, readback mismatch");
  $finish;
 end
 initial begin #1000000000; $fatal(1,"PCA testbench timeout: %h state %d step %d",status,dut.state,dut.step); end
endmodule
