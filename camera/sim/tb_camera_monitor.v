`timescale 1ns/1ps
module tb_camera_monitor;
 reg clk=0,pclk=0,pclk_enable=1,reset=1,vs=1,href=1;
 wire [255:0] report;
 reg [255:0] previous;
 integer y,x;
 always #10 clk=~clk;
 always #7 if(pclk_enable) pclk=~pclk;
 camera_monitor #(.CLOCK_HZ(200),.WIDTH(8),.HEIGHT(4)) dut(
  .clk(clk),.pclk(pclk),.reset(reset),.vsync(vs),.href(href),.report(report));
 task frame(input integer row_bytes,input reg inverted);
  begin
   for(y=0;y<4;y=y+1) begin
    href=1;
    repeat(row_bytes) @(negedge pclk);
    href=0; repeat(4) @(negedge pclk);
   end
   vs=!inverted; repeat(4) @(negedge pclk);
   vs=inverted; repeat(4) @(negedge pclk);
  end
 endtask
 task snapshot_wait;
  begin repeat(450) @(negedge clk); end
 endtask
 initial begin
  repeat(8) @(negedge pclk); reset=0;
  // Release reset in the middle of a high VSYNC/partial line: ignore it.
  repeat(8) @(negedge pclk); href=0; vs=0; repeat(4) @(negedge pclk);
  if(dut.total_frames!=0) $fatal(1,"partial startup counted as a frame");
  vs=1; repeat(4) @(negedge pclk); vs=0; repeat(4) @(negedge pclk);
  frame(16,0); frame(16,0); frame(15,0); frame(16,0); frame(16,0);
  snapshot_wait;
  if(report[255:240]!=16'h4456 || report[239:224]==0) $fatal(1,"snapshot handshake");
  if(report[159:128]!=5 || report[127:96]!=1) $fatal(1,"all-frame counters wrong: %h",report);
  if(report[95:64]!=64 || report[63:48]!=4 || report[47:32]!=16 || report[31:0]!=88)
   $fatal(1,"complete-frame metadata wrong: %h",report);
  previous=report;
  // New malformed partial row must not corrupt metadata of the last full frame.
  href=1; repeat(9) @(negedge pclk); href=0;
  snapshot_wait;
  if(report[95:0]!=previous[95:0]) $fatal(1,"snapshot mixed current/previous frame");
  if(report[223:192]<=previous[223:192] || report[191:160]<=previous[191:160])
   $fatal(1,"clock counters did not advance");
  @(negedge pclk); pclk_enable=0;
  snapshot_wait; previous=report; snapshot_wait;
  if(report!==previous) $fatal(1,"stopped PCLK produced a fresh snapshot");
  pclk_enable=1; snapshot_wait;
  if(report[239:224]==previous[239:224]) $fatal(1,"snapshot failed to recover after PCLK stopped");
  reset=1; repeat(8) @(negedge pclk); vs=0; href=0; reset=0;
  repeat(8) @(negedge pclk); vs=1; repeat(4) @(negedge pclk);
  frame(16,1); frame(16,1); snapshot_wait;
  if(report[159:128]!=2 || report[127:96]!=0 || report[95:64]!=64)
   $fatal(1,"high-VSYNC/reset recovery incorrect: %h",report);
  $display("ALL CAMERA MONITOR TESTS PASS: all frames, bad row, both VSYNC polarities, coherent snapshot, stop/recovery");
  $finish;
 end
 initial begin #200000; $fatal(1,"monitor timeout"); end
endmodule
