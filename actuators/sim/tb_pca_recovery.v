`timescale 1ns/1ps
module tb_pca_recovery;
 reg clk=0,resetn=0,hold_scl=0,hold_sda=0,watch_clear=0,watch_motion=0,motion_seen=0;
 always #500 clk=~clk;
 reg [31:0] control=0;
 reg [7:0] token=0;
 reg [15:0] first_failure;
 tri1 scl,sda;
 wire [63:0] status,diagnostics;
 integer clear_clocks=0,i;
 pca_bench_core #(.CLOCK_HZ(1000000),.BUS_HZ(100000),
  .PULSE_CYCLES(30000),.RETRY_CYCLES(1000)) dut(
  .clk(clk),.resetn(resetn),.control(control),.scl(scl),.sda(sda),
  .status(status),.diagnostics(diagnostics));
 pca9685_model chip(.present(1'b1),.hold_scl(hold_scl),.hold_sda(hold_sda),
  .bad_prescale(1'b0),.scl(scl),.sda(sda));
 always @(posedge scl) if(watch_clear && dut.bus.state==27) clear_clocks=clear_clocks+1;
 always @(negedge clk) if(watch_motion && !chip.registers[21][4]) motion_seen=1;
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
    if(chip.registers[9+4*i][4]!==1) $fatal(1,"Recovery left channel %d enabled",i);
  end
 endtask
 task init_ok;
  begin
   send(2,0,0); idle; all_off;
   if(!status[0] || status[27:24] || diagnostics[31:16]) $fatal(1,"Init did not clear fault");
  end
 endtask
 initial begin
  repeat(5) @(negedge clk); resetn=1; idle; init_ok;
  // Simulate a target which releases SDA only after nine recovery clocks.
  hold_sda=1; watch_clear=1; watch_motion=1;
  send(4,3,348);
  wait(clear_clocks==9); @(negedge scl); hold_sda=0;
  idle; all_off; watch_clear=0; watch_motion=0;
  if(clear_clocks!=9 || motion_seen || status[0] || status[27:24]!=2)
   $fatal(1,"Bus clear replayed motion or did not produce nine clocks/fault");
  first_failure=diagnostics[31:16];
  if(first_failure==0) $fatal(1,"Missing recovery fault evidence");
  $display("PASS nine recovery clocks, STOP, all-off verification, no actuator replay");

  // A physical short cannot be repaired by clocks. Never claim safe shutdown.
  init_ok; send(4,3,348); wait(status[1]); idle; hold_sda=1;
  wait(status[27:24]==2); repeat(14000) @(negedge clk);
  if(!status[1] || !status[3] || status[0] || chip.registers[21][4])
   $fatal(1,"Hard SDA fault falsely confirmed shutdown");
  first_failure=diagnostics[31:16]; hold_scl=1;
  repeat(25000) @(negedge clk);
  if(diagnostics[31:16]!==first_failure) $fatal(1,"Retries overwrote first failure");
  hold_sda=0; repeat(10) @(negedge clk); hold_scl=0;
  idle; all_off;
  if(status[1] || status[0]) $fatal(1,"Recovery failed shutdown or automatically rearmed");
  $display("PASS hard SDA/SCL faults remain bounded and unconfirmed, first failure retained");

  // Reset the controller in the middle of reading zero bits. The real wire
  // model stays in a read and holds SDA low until clocked out of that byte.
  init_ok; send(3,0,0);
  wait(chip.reading && chip.bits==2); @(negedge clk);
  resetn=0; control=0; token=0;
  repeat(5) @(negedge clk); resetn=1;
  wait(status[27:24]==2); idle; all_off;
  if(sda!==1 || status[0] || status[1]) $fatal(1,"Interrupted target read not recovered");
  init_ok;
  $display("ALL PCA RECOVERY TESTS PASS: interrupted target read recovers without power cycling");
  $finish;
 end
 initial begin #1000000000; $fatal(1,"Recovery timeout: %h bus=%d clocks=%d",status,dut.bus.state,clear_clocks); end
endmodule
