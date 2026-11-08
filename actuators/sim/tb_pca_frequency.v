`timescale 1ns/1ps
module tb_pca_frequency;
 reg clk=0,resetn=0;
 always #500 clk=~clk;
 reg [31:0] control=0;
 reg [7:0] token=0;
 tri1 scl,sda;
 wire [63:0] status,diagnostics;
 integer i;
 pca_bench_core #(.CLOCK_HZ(1000000),.BUS_HZ(100000),.PULSE_CYCLES(30000),
  .RETRY_CYCLES(1000),.ESC_ARM_CYCLES(40000),.ESC_TEST_CYCLES(6000),.ESC_RETURN_CYCLES(15000)) dut(
  .clk(clk),.resetn(resetn),.control(control),.scl(scl),.sda(sda),.status(status),.diagnostics(diagnostics));
 pca9685_model chip(.present(1'b1),.hold_scl(1'b0),.hold_sda(1'b0),
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
  begin
   for(i=0;i<16;i=i+1)
    if(chip.registers[9+4*i][4]!==1) $fatal(1,"Frequency change left output enabled");
  end
 endtask
 task init_hz;
  input [15:0] hz;
  begin
   send(2,0,hz); idle; all_off;
   if(!status[0] || status[27:24]) $fatal(1,"Frequency initialization failed");
   if(chip.registers[254] !== (hz==60 ? 8'd101 : 8'd121)) $fatal(1,"Wrong prescaler");
  end
 endtask
 initial begin
  repeat(5) @(negedge clk); resetn=1; idle; init_hz(60);
  send(5,0,307); idle; all_off;
  if(status[27:24]!=3) $fatal(1,"Old 50 Hz neutral ticks accepted at 60 Hz");
  init_hz(60); send(5,0,368);
  wait(chip.registers[9]===1);
  if(chip.registers[8]!==8'h70) $fatal(1,"Wrong 1500 us neutral ticks at 60 Hz");
  wait(status[4]); idle; all_off;
  send(6,0,372); wait(chip.registers[9]===1);
  wait(chip.registers[8]===8'h74);
  if(chip.registers[9]!==1) $fatal(1,"60 Hz throttle transition disabled signal");
  wait(chip.registers[8]===8'h70);
  wait(status[4]); idle; all_off;
  if(status[27:24]) $fatal(1,"60 Hz sequence failed");
  $display("PASS 60 Hz initialization, neutral and throttle/return sequence at recalculated ticks");

  // Changing frequency revokes the completed neutral test, including 60->50->60.
  init_hz(50); init_hz(60); send(6,0,372); idle; all_off;
  if(status[27:24]!=4) $fatal(1,"Frequency change retained ESC qualification");
  init_hz(60); send(4,7,293); idle; all_off;
  if(status[27:24]!=3) $fatal(1,"60 Hz general pulse lower bound ignored");
  init_hz(60); send(4,3,634); wait(status[1]); idle;
  if(chip.registers[20]!==8'h7a || chip.registers[21]!==2) $fatal(1,"Steering width not preserved at 60 Hz");
  // A frequency command during output stops it and must not alter PRE_SCALE.
  send(2,0,50); idle; all_off;
  if(status[27:24]!=3 || chip.registers[254]!==101) $fatal(1,"Live frequency change accepted");
  init_hz(60); send(4,3,635); idle; all_off;
  if(status[27:24]!=3) $fatal(1,"60 Hz steering upper bound ignored");
  init_hz(60); send(6,0,442); idle; all_off;
  if(status[27:24]!=4) $fatal(1,"Unqualified ESC trial accepted");
  send(2,0,55); idle; all_off;
  if(status[27:24]!=3 || chip.registers[254]!==101) $fatal(1,"Unsupported frequency accepted");
  init_hz(0);
  if(status[47:40]!=9) $fatal(1,"Wrong firmware version");
  $display("ALL PCA FREQUENCY TESTS PASS: bounds, idle-only changes, qualification reset, legacy INIT=50 Hz");
  $finish;
 end
 initial begin #1000000000; $fatal(1,"Frequency simulation timeout %h",status); end
endmodule
