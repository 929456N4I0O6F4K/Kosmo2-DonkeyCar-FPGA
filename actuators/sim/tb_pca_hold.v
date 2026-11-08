`timescale 1ns/1ps
module tb_pca_hold;
 reg clk=0,resetn=0,hold_scl=0;
 always #500 clk=~clk;
 reg [31:0] control=0;
 reg [7:0] token=0;
 tri1 scl,sda;
 wire [63:0] status,diagnostics;
 integer i,n,old_writes;
 time neutral_at,target_at,returned_at;
 pca_bench_core #(.CLOCK_HZ(1000000),.BUS_HZ(100000),.PULSE_CYCLES(30000),
  .RETRY_CYCLES(1000),.ESC_ARM_CYCLES(40000),.ESC_TEST_CYCLES(6000),.ESC_RETURN_CYCLES(15000)) dut(
  .clk(clk),.resetn(resetn),.control(control),.scl(scl),.sda(sda),.status(status),.diagnostics(diagnostics));
 pca9685_model chip(.present(1'b1),.hold_scl(hold_scl),.hold_sda(1'b0),
  .bad_prescale(1'b0),.scl(scl),.sda(sda));
 task idle;
  begin wait(!status[2] && !status[3]); repeat(10) @(negedge clk); end
 endtask
 task send;
  input [3:0] op,ch; input [15:0] data;
  begin
   @(negedge clk); token=token+1'b1; control={token,op,ch,data};
   wait(status[39:32]==token); repeat(10) @(negedge clk);
  end
 endtask
 task all_off;
  begin for(i=0;i<16;i=i+1)
   if(chip.registers[9+4*i][4]!==1) $fatal(1,"Hold left output enabled on %d",i);
  end
 endtask
 task only_esc;
  begin for(i=1;i<16;i=i+1)
   if(chip.registers[9+4*i][4]!==1) $fatal(1,"Hold enabled another channel %d",i);
  end
 endtask
 task prepare;
  begin
   send(2,0,60); idle; all_off;
   send(5,0,380); wait(status[4]); idle; all_off;
   if(status[27:24] || !status[0]) $fatal(1,"Hold preparation failed");
  end
 endtask
 task verify_hold;
  input [3:0] seconds_code;
  input integer expected_ns;
  begin
   send(7,0,{seconds_code,12'd406});
   wait(chip.registers[9]===1); neutral_at=$time;
   if(chip.registers[8]!==8'h7c) $fatal(1,"Hold did not begin at 1550 us");
   only_esc;
   wait(chip.registers[8]===8'h96); target_at=$time;
   if(target_at-neutral_at<39000000 || target_at-neutral_at>42000000)
    $fatal(1,"Hold initial neutral duration wrong");
   if(chip.registers[9]!==1 || status[31:28]!=7) $fatal(1,"Hold target gap or opcode");
   only_esc;
   // No host commands are sent while the FPGA times target, return and off.
   wait(chip.registers[8]===8'h7c); returned_at=$time;
   if(returned_at-target_at<expected_ns-1000000 || returned_at-target_at>expected_ns+2000000)
    $fatal(1,"Hold duration %d incorrect: %t",seconds_code,returned_at-target_at);
   if(chip.registers[9]!==1) $fatal(1,"Hold return interrupted PWM");
   wait(chip.registers[9][4]);
   if($time-returned_at<14000000 || $time-returned_at>17000000)
    $fatal(1,"Hold return-to-neutral duration wrong");
   idle; all_off;
   if(status[27:24] || !status[4] || status[1] || status[17:16]!=0)
    $fatal(1,"Hold completion not clean");
   old_writes=chip.writes; repeat(70000) @(negedge clk);
   if(chip.writes!=old_writes) $fatal(1,"Hold replayed without a new command");
  end
 endtask
 task reject;
  input [3:0] ch; input [15:0] value;
  begin
   prepare; send(7,ch,value); idle; all_off;
   if(status[27:24]!=3) $fatal(1,"Invalid hold accepted: %h",value);
  end
 endtask
 initial begin
  repeat(5) @(negedge clk); resetn=1; idle;
  if(status[47:40]!=9) $fatal(1,"Wrong hold firmware version");
  send(7,0,16'h5196); idle; all_off;
  if(status[27:24]!=4) $fatal(1,"Uninitialized hold accepted");
  send(2,0,60); idle; send(7,0,16'h5196); idle; all_off;
  if(status[27:24]!=4) $fatal(1,"Unqualified hold accepted");
  prepare;
  verify_hold(1,12000000); verify_hold(2,24000000); verify_hold(5,60000000);
  $display("PASS 1/2/5-second-scaled holds, fixed pulse, isolation, autonomous return/off and no replay");

  // An old half-second command after a long hold must restore its short timer.
  send(6,0,406); wait(chip.registers[8]===8'h96); target_at=$time;
  wait(chip.registers[8]===8'h7c);
  if($time-target_at<5000000 || $time-target_at>8000000) $fatal(1,"Legacy trial inherited long duration");
  wait(status[4]); idle; all_off;
  reject(0,16'h0196); reject(0,16'h3196); reject(0,16'hf196);
  reject(0,16'h1195); reject(0,16'h1197); reject(3,16'h1196);
  send(2,0,60); idle; send(5,0,368); wait(status[4]); idle;
  send(7,0,16'h1196); idle; all_off;
  if(status[27:24]!=3) $fatal(1,"Wrong hold neutral accepted");
  send(2,0,50); idle; send(5,0,307); wait(status[4]); idle;
  send(7,0,16'h1196); idle; all_off;
  if(status[27:24]!=3) $fatal(1,"50 Hz hold accepted");
  $display("PASS duration whitelist, fixed neutral/target/frequency/channel, legacy duration independence");

  for(n=1;n<=3;n=n+1) begin
   prepare; send(7,0,16'h5196); wait(status[17:16]==n); idle;
   send(1,0,0); idle; all_off;
   repeat(70000) @(negedge clk); all_off;
   send(7,0,16'h1196); idle;
   if(status[27:24]!=4) $fatal(1,"Interrupted hold retained neutral qualification");
  end
  prepare; send(7,0,16'h5196); wait(chip.registers[8]===8'h96); idle;
  send(7,0,16'h5196); idle; all_off;
  if(status[27:24]!=3) $fatal(1,"Fresh command extended a running hold");
  prepare; send(7,0,16'h5196); wait(chip.registers[8]===8'h96);
  resetn=0; control=0; token=0; repeat(5) @(negedge clk); resetn=1;
  idle; all_off;
  if(status[0]) $fatal(1,"Reset retained ready");
  prepare; send(7,0,16'h5196); wait(chip.registers[8]===8'h96); hold_scl=1;
  wait(status[27:24]==2);
  if(!status[3] || !status[1] || status[0]) $fatal(1,"Bus fault falsely reported shutdown");
  hold_scl=0; idle; all_off;
  send(2,0,60); idle; send(7,0,16'h1196); idle;
  if(status[27:24]!=4) $fatal(1,"Fault retained hold qualification");
  $display("ALL PCA HOLD TESTS PASS: OFF in all phases, retrigger, reset and bus-fault recovery");
  $finish;
 end
 initial begin repeat(10) #1000000000; $fatal(1,"Hold simulation timeout %h",status); end
endmodule
