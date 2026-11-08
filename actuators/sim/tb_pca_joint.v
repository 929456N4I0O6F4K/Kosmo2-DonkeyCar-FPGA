`timescale 1ns/1ps
module tb_pca_joint;
 reg clk=0,resetn=0,hold_scl=0,monitor_pair=0;
 always #500 clk=~clk;
 reg [31:0] control=0;
 reg [7:0] token=0;
 tri1 scl,sda;
 wire [63:0] status,diagnostics;
 integer i,n,old_writes;
 reg [11:0] expected_center=415;
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
   if(chip.registers[9+4*i][4]!==1) $fatal(1,"Joint left output enabled on %d",i);
  end
 endtask
 task prepare;
  begin
   monitor_pair=0;
   send(2,0,60); idle; all_off;
   expected_center=415;
   if(dut.joint_center!==415) $fatal(1,"INIT failed to restore default center");
   send(5,0,380); wait(status[4]); idle; all_off;
   if(status[27:24] || !status[0]) $fatal(1,"Joint preparation failed");
  end
 endtask
 // Check both outputs continuously, not just at the endpoints of the sequence.
 always @(negedge clk) if(monitor_pair && status[17:16]!=0) begin
  if(chip.registers[9]!==1 || chip.registers[21]!==1)
   $fatal(1,"Joint phase inserted a signal gap");
  for(integer j=1;j<16;j=j+1) if(j!=3 && chip.registers[9+4*j][4]!==1)
   $fatal(1,"Joint enabled unselected channel %d",j);
  if(status[31:28]==8 && chip.registers[8]!==8'h7c)
   $fatal(1,"Stationary steering changed ESC neutral");
 end
 task verify_joint;
  input [3:0] op,duration; input [11:0] steering;
  input integer expected_ns;
  begin
   send(op,0,{duration,steering});
   wait(chip.registers[9]===1); neutral_at=$time;
   wait(chip.registers[21]===1);
   if(chip.registers[8]!==8'h7c || chip.registers[20]!==expected_center[7:0])
    $fatal(1,"Joint initial pair is not neutral/center");
   monitor_pair=1;
   wait(status[17:16]==2); target_at=$time;
   idle;
   if(target_at-neutral_at<39000000 || target_at-neutral_at>42000000)
    $fatal(1,"Joint initial neutral duration wrong");
   if(chip.registers[8] !== (op==9 ? 8'h96 : 8'h7c) || chip.registers[20]!==steering[7:0])
    $fatal(1,"Joint target pair wrong");
   // No host activity during this sequence. Timed return must be autonomous.
   wait(status[17:16]==3); returned_at=$time;
   if(returned_at-target_at<expected_ns-1000000 || returned_at-target_at>expected_ns+2000000)
    $fatal(1,"Joint target duration wrong: %t",returned_at-target_at);
   idle;
   if(chip.registers[8]!==8'h7c || chip.registers[20]!==expected_center[7:0])
    $fatal(1,"Joint return pair wrong");
   wait(chip.registers[9][4]);
   if($time-returned_at<14000000 || $time-returned_at>18000000)
    $fatal(1,"Joint return dwell wrong");
   idle; monitor_pair=0; all_off;
   if(status[27:24] || !status[4] || status[1]) $fatal(1,"Joint completion not clean");
   old_writes=chip.writes; repeat(70000) @(negedge clk);
   if(chip.writes!=old_writes) $fatal(1,"Joint command replayed");
  end
 endtask
 task configure_center;
  input [11:0] value;
  begin
   old_writes=chip.writes;
   send(11,3,value); idle; all_off;
   if(status[27:24] || status[31:28]!=11 || status[23:16]!=value[7:0] ||
      dut.joint_center!==value || chip.writes!=old_writes || status[1])
    $fatal(1,"Center configuration did not acknowledge without enabling outputs");
   expected_center=value;
  end
 endtask
 task reject;
  input [3:0] op,ch; input [15:0] value;
  begin
   prepare; send(op,ch,value); idle; all_off;
   if(status[27:24]!=3) $fatal(1,"Invalid joint command accepted %h %h",op,value);
  end
 endtask
 initial begin
  repeat(5) @(negedge clk); resetn=1; idle;
  if(status[47:40]!=9) $fatal(1,"Wrong joint firmware version");
  send(11,3,418); idle; all_off;
  if(status[27:24]!=4) $fatal(1,"Uninitialized center configuration accepted");
  send(9,0,16'h019f); idle; all_off;
  if(status[27:24]!=4) $fatal(1,"Uninitialized joint drive accepted");
  send(2,0,60); idle; send(8,0,16'h219f); idle; all_off;
  if(status[27:24]!=4) $fatal(1,"Unqualified joint steer accepted");
  prepare;
  verify_joint(8,2,415,24000000);
  verify_joint(8,2,391,24000000);
  verify_joint(8,2,440,24000000);
  verify_joint(9,0,415,6000000);
  verify_joint(9,1,391,12000000);
  verify_joint(9,2,440,24000000);
  // v8 widened steering stays in OFF_H=1 at both ends and accepts interior values.
  verify_joint(8,2,365,24000000);
  verify_joint(8,2,488,24000000);
  verify_joint(9,0,365,6000000);
  verify_joint(9,1,488,12000000);
  verify_joint(9,2,463,24000000);
  configure_center(418);
  verify_joint(8,2,391,24000000);
  verify_joint(9,0,440,6000000);
  configure_center(404); verify_joint(8,2,365,24000000);
  configure_center(429); verify_joint(9,0,488,6000000);
  // v9 accepts the next outer trial range, with the latest observed center.
  configure_center(428);
  verify_joint(8,2,355,24000000); verify_joint(8,2,500,24000000);
  verify_joint(9,0,355,6000000); verify_joint(9,2,500,24000000);
  verify_joint(8,2,360,24000000); verify_joint(8,2,493,24000000);
  $display("PASS joint v9 endpoints, 1745 us initial/return center, unchanged timing, no gaps and autonomous off");
  reject(8,0,16'h119f); reject(8,0,16'h019f);
  reject(9,0,16'h319f); reject(9,0,16'h519f); reject(9,0,16'hf19f);
  reject(9,3,16'h019f); reject(9,0,16'h0162); reject(9,0,16'h01f5);
  reject(8,0,16'h2162); reject(8,0,16'h21f5);
  reject(10,0,16'h019f);
  reject(11,0,418); reject(11,3,403); reject(11,3,430); reject(11,3,16'h119f);
  send(2,0,60); idle; send(5,0,368); wait(status[4]); idle;
  send(9,0,16'h019f); idle; all_off;
  if(status[27:24]!=3) $fatal(1,"Joint with wrong neutral accepted");
  send(2,0,50); idle; send(5,0,307); wait(status[4]); idle;
  send(11,3,418); idle; all_off;
  if(status[27:24]!=3) $fatal(1,"Center configuration at 50 Hz accepted");
  send(9,0,16'h019f); idle; all_off;
  if(status[27:24]!=3) $fatal(1,"Joint at 50 Hz accepted");
  $display("PASS joint frequency, neutral, channel, position and duration restrictions");

  for(n=1;n<=3;n=n+1) begin
   prepare; send(9,0,16'h21b8); wait(status[17:16]==n); idle;
   send(1,0,0); idle; all_off;
   repeat(70000) @(negedge clk); all_off;
   send(9,0,16'h019f); idle;
   if(status[27:24]!=4) $fatal(1,"Interrupted joint retained qualification");
  end
  prepare; send(9,0,16'h21b8); wait(chip.registers[8]===8'h96); idle;
  send(9,0,16'h21b8); idle; all_off;
  if(status[27:24]!=3) $fatal(1,"Joint drive retrigger did not abort");
  prepare; configure_center(418); send(9,0,16'h21b8); wait(status[17:16]==2); idle;
  send(11,3,420); idle; all_off;
  if(status[27:24]!=3 || dut.joint_center!==418) $fatal(1,"Active center change did not abort");
  prepare; send(9,0,16'h21b8); wait(chip.registers[8]===8'h96);
  resetn=0; control=0; token=0; repeat(5) @(negedge clk); resetn=1;
  idle; all_off;
  if(status[0] || dut.joint_center!==415) $fatal(1,"Joint reset retained ready or custom center");

  // Fault between ESC and servo target writes must not report an orderly stop.
  prepare; send(9,0,16'h21b8); wait(chip.registers[8]===8'h96); hold_scl=1;
  wait(status[27:24]==2);
  if(!status[3] || !status[1] || status[0]) $fatal(1,"Joint bus fault falsely reported shutdown");
  hold_scl=0; idle; all_off;
  send(2,0,60); idle; send(9,0,16'h019f); idle;
  if(status[27:24]!=4) $fatal(1,"Joint fault retained qualification");

  prepare; send(8,0,16'h2187);
  wait(dut.operation==10 && dut.step==16 && dut.state==1);
  chip.registers[21]=8'h10;
  wait(status[27:24]==5); idle; all_off;
  if(status[0]) $fatal(1,"Servo readback mismatch retained ready");

  // Existing single-channel commands must still isolate outputs after joint use.
  prepare; send(9,0,16'h019f); wait(status[4]); idle;
  send(6,0,406); wait(chip.registers[8]===8'h96); target_at=$time;
  if(chip.registers[21][4]!==1) $fatal(1,"Legacy ESC enabled servo after joint");
  wait(chip.registers[8]===8'h7c);
  if($time-target_at<5000000 || $time-target_at>8000000) $fatal(1,"Legacy ESC inherited joint duration");
  wait(status[4]); idle; all_off;
  send(4,3,415); wait(chip.registers[21]===1);
  if(chip.registers[9][4]!==1) $fatal(1,"Legacy servo enabled ESC after joint");
  wait(status[4]); idle; all_off;
  $display("ALL PCA JOINT TESTS PASS: all-phase OFF, retrigger, PA reset, partial-write bus fault, readback mismatch and legacy isolation");
  $finish;
 end
 initial begin repeat(10) #1000000000; $fatal(1,"Joint simulation timeout %h",status); end
endmodule
