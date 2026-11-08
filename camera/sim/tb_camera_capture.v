`timescale 1ns/1ps
module tb_camera_capture;
 reg pclk=0, clk=0, reset_async=1, arm=0, vs=0, href=0;
 reg [7:0] data=0;
 reg [15:0] rd_addr=0;
 wire [7:0] rd_data;
 wire done,good,beat;
 wire [31:0] bytes_seen;
 wire [15:0] lines,last_line;
 wire [3:0] errors;
 integer i;
 always #7 pclk=~pclk;
 always #5 clk=~clk;
 camera_capture dut(.pclk(pclk),.reset_async(reset_async),.arm(arm),.vsync(vs),.href(href),.data(data),
 .rd_clk(clk),.rd_addr(rd_addr),.rd_data(rd_data),.done(done),.good(good),.byte_count(bytes_seen),
 .line_count(lines),.last_line_bytes(last_line),.error_flags(errors),.pclk_heartbeat(beat));
 task begin_request;
  begin
   @(negedge pclk); arm=0; vs=0; href=0; repeat(8) @(negedge pclk);
   arm=1; repeat(8) @(negedge pclk);
  end
 endtask
 task frame_polarity(input integer row_count,input integer row_bytes,input reg inverted);
  integer y,x;
  begin
   vs=!inverted; repeat(4) @(negedge pclk); vs=inverted; repeat(4) @(negedge pclk);
   for(y=0;y<row_count;y=y+1) begin
    for(x=0;x<row_bytes;x=x+1) begin
     href=1; data=((y*row_bytes+x)^8'ha5); @(negedge pclk);
    end
    href=0; repeat(4) @(negedge pclk);
   end
   repeat(8) @(negedge pclk); vs=!inverted; repeat(4) @(negedge pclk); vs=inverted;
   repeat(4) @(negedge pclk);
  end
 endtask
 task frame(input integer row_count,input integer row_bytes);
  begin frame_polarity(row_count,row_bytes,0); end
 endtask
 initial begin
  #100; reset_async=0; begin_request;
  // A partial line before the next VSYNC must be ignored.
  href=1; data=8'h55; repeat(17) @(negedge pclk); href=0;
  frame(120,320); wait(done);
  if(!good || bytes_seen!=38400 || lines!=120 || last_line!=320 || errors) $fatal(1,"full frame metadata wrong");
  for(i=0;i<38400;i=i+1) begin
   @(negedge clk); rd_addr=i; @(posedge clk); #1;
   if(rd_data!==((i^8'ha5)&255)) $fatal(1,"frame RAM mismatch at %d",i);
  end
  // While the completed buffer is held, another frame cannot overwrite it.
  data=8'h55; href=1; repeat(100) @(negedge pclk); href=0;
  rd_addr=0; repeat(2) @(posedge clk); #1;
  if(rd_data!==8'ha5) $fatal(1,"completed frame overwritten");
  $display("PASS full 160x120 frame: all 38400 bytes, partial-frame skip and frozen buffer");
  begin_request; frame(119,320); wait(done);
  if(good || !errors[1]) $fatal(1,"short frame accepted");
  $display("PASS missing row rejected");
  begin_request; frame(120,319); wait(done);
  if(good || !errors[2]) $fatal(1,"short rows accepted");
  $display("PASS 319-byte rows rejected");
  begin_request; frame(121,320); wait(done);
  if(good || !errors[3] || bytes_seen!=38720) $fatal(1,"overflow not bounded/reported");
  $display("PASS overflow bounded and reported");
  begin_request; frame(120,320); wait(done);
  if(!good || errors) $fatal(1,"capture did not recover");
  begin_request; frame_polarity(120,320,1); wait(done);
  if(!good || bytes_seen!=38400 || lines!=120 || last_line!=320 || errors)
   $fatal(1,"valid rows with high VSYNC rejected");
  for(i=0;i<38400;i=i+1) begin
   @(negedge clk); rd_addr=i; @(posedge clk); #1;
   if(rd_data!==((i^8'ha5)&255)) $fatal(1,"high-VSYNC frame RAM mismatch at %d",i);
  end
  $display("PASS high VSYNC during valid rows: full frame metadata and all 38400 bytes");
  $display("ALL CAMERA CAPTURE TESTS PASS"); $finish;
 end
 initial begin #20000000; $fatal(1,"capture test timed out"); end
endmodule
