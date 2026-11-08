`timescale 1ns/1ps
module tb_camera_top;
 localparam W=8,H=4,CPB=10;
 reg clk=0,pclk=0,rstn=0,rx=1,vs=0,href=0;
 reg [7:0] data=0;
 reg present=0,bad_id=0,hold_scl=0,run_pclk=1,run_frames=0,short_line=0;
 wire tx; wire [4:0] leds; wire cam_rst;
 tri1 scl,sda;
 always #5 clk=~clk;
 always #7 if(run_pclk) pclk=~pclk;
 camera_top #(.CLOCK_HZ(1000000),.UART_BAUD(100000),.SCCB_HZ(50000),
  .WIDTH(W),.HEIGHT(H),.RESET_CYCLES(16),.CAPTURE_TIMEOUT_CYCLES(100000)) dut(
  .sysclk_50(clk),.rstn(rstn),.uart_rx(rx),.uart_tx(tx),.led_n(leds),
  .cam_pclk(pclk),.cam_vsync(vs),.cam_href(href),.cam_data(data),
  .cam_reset_n(cam_rst),.cam_scl(scl),.cam_sda(sda));
 ov2640_model sensor(.present(present),.bad_id(bad_id),.hold_scl(hold_scl),.scl(scl),.sda(sda));
 reg [7:0] received[0:65535]; integer rx_count=0, k; reg [7:0] rx_byte;
 // Independent UART decoder samples at centers of wire bits.
 always @(negedge tx) begin
  #50; if(tx!==0) $fatal(1,"bad UART start");
  for(k=0;k<8;k=k+1) begin #100; rx_byte[k]=tx; end
  #100; if(tx!==1) $fatal(1,"bad UART stop");
  received[rx_count]=rx_byte; rx_count=rx_count+1;
 end
 task command(input [7:0] c);
  integer b;
  begin
   @(negedge clk); rx=0; repeat(CPB) @(negedge clk);
   for(b=0;b<8;b=b+1) begin rx=c[b]; repeat(CPB) @(negedge clk); end
   rx=1; repeat(CPB) @(negedge clk);
  end
 endtask
 function [31:0] checksum(input integer offset,input integer count);
  integer a,b; reg [31:0] c;
  begin
   c=32'hffffffff;
   for(a=0;a<count;a=a+1) begin
    c=c^received[offset+a];
    for(b=0;b<8;b=b+1) if(c[0]) c=(c>>1)^32'hedb88320; else c=c>>1;
   end
   checksum=~c;
  end
 endfunction
 task response(input integer offset,input integer kind,input integer err);
  integer n,total; reg [31:0] got_crc;
  begin
   wait(rx_count>=offset+40);
   if({received[offset+3],received[offset+2],received[offset+1],received[offset]}!==32'h314d4143) $fatal(1,"bad magic");
   n={received[offset+19],received[offset+18],received[offset+17],received[offset+16]};
   total=40+n; wait(rx_count>=offset+total+4);
   got_crc={received[offset+total+3],received[offset+total+2],received[offset+total+1],received[offset+total]};
   if(checksum(offset,total)!==got_crc) $fatal(1,"bad CRC");
   if(received[offset+5]!=kind || received[offset+7]!=err)
    $fatal(1,"response kind/error got %0d/%0d expected %0d/%0d",received[offset+5],received[offset+7],kind,err);
   if(kind==2 && n!=W*H*2) $fatal(1,"wrong payload size");
   repeat(30) @(posedge clk);
  end
 endtask
 integer y,x,seed=0,offset,j,fd;
 initial forever begin
  wait(run_frames && dut.cfg_ready && run_pclk);
  @(negedge pclk); vs=1; href=0; repeat(4) @(negedge pclk);
  vs=0; repeat(4) @(negedge pclk);
  for(y=0;y<H;y=y+1) begin
   for(x=0;x<(W*2-((short_line && y==H-1)?1:0));x=x+1) begin
    href=1; data=seed+y*W*2+x; @(negedge pclk);
   end
   href=0; repeat(4) @(negedge pclk);
  end
  seed=seed+1; repeat(8) @(negedge pclk);
 end
 initial begin
  #100; rstn=1;
  wait(dut.cfg_failed); offset=rx_count; command("S"); response(offset,1,1);
  if(received[offset+6]&1) $fatal(1,"absent camera marked ready");
  if(dut.cfg_debug[20:16]!==10 || dut.cfg_debug[22:21]!==2'b11)
   $fatal(1,"NACK diagnostic did not record released-high bus at ACK");
  $display("PASS disconnected SCCB NACK/status");
  present=1; offset=rx_count; command("R"); response(offset,1,0);
  wait(dut.cfg_ready || dut.cfg_failed);
  if(dut.cfg_failed || dut.pid!==8'h26 || dut.ver!==8'h42) $fatal(1,"probe/config failed pid=%h ver=%h error=%d",dut.pid,dut.ver,dut.cfg_error);
  if(sensor.registers[8'hda]!==8'h08 || sensor.registers[8'h5a]!==8'd40 || sensor.registers[8'h5b]!==8'd30)
   $fatal(1,"RGB565/QQVGA register writes wrong");
  $display("PASS ID 2642 and complete init (%0d writes)",sensor.writes);
  run_frames=1; offset=rx_count; command("F"); response(offset,2,0);
  for(j=0;j<W*H*2;j=j+1) if(received[offset+40+j]!==((received[offset+40]+j)&255)) $fatal(1,"frame torn or byte lost at %d",j);
  fd=$fopen("frame_packet.hex","w");
  for(j=0;j<40+W*H*2+4;j=j+1) $fdisplay(fd,"%02x",received[offset+j]);
  $fclose(fd);
  $display("PASS fresh frame, frozen RAM and UART CRC");
  short_line=1; repeat(2000) @(posedge clk);
  offset=rx_count; command("F"); response(offset,3,5);
  if(!(received[offset+31]&4)) $fatal(1,"short line not reported");
  $display("PASS short line rejected");
  run_frames=0; repeat(2000) @(posedge clk); run_pclk=0;
  offset=rx_count; command("F"); response(offset,3,6);
  $display("PASS missing PCLK timeout");
  run_pclk=1; short_line=0; run_frames=1;
  offset=rx_count; command("F"); response(offset,2,0);
  $display("PASS capture recovers after timeout");
  offset=rx_count; command("T"); response(offset,1,0); wait(dut.cfg_ready);
  if(sensor.registers[9'h112]!==8'h22) $fatal(1,"colorbar not set");
  offset=rx_count; command("N"); response(offset,1,0); wait(dut.cfg_ready);
  if(sensor.registers[9'h112]!==8'h20) $fatal(1,"colorbar not cleared");
  $display("PASS sensor colorbar and normal mode");
  bad_id=1; offset=rx_count; command("R"); response(offset,1,0); wait(dut.cfg_failed);
  if(dut.cfg_error!==3) $fatal(1,"wrong ID not rejected");
  bad_id=0; hold_scl=1; offset=rx_count; command("R"); response(offset,1,0); wait(dut.cfg_failed);
  if(dut.cfg_error!==2) $fatal(1,"stuck bus not timed out");
  if(dut.cfg_debug[20:16]!==1 || dut.cfg_debug[24:21]!==4'b0001 || !dut.cfg_debug[35])
   $fatal(1,"timeout diagnostic did not record SCL low, SDA high, released drivers, reset high");
  $display("PASS wrong sensor ID and stuck SCL errors");
  hold_scl=0; repeat(10) @(posedge clk);
  if(dut.cfg_debug[6:5]!==2'b11 || dut.cfg_debug[22:21]!==2'b01)
   $fatal(1,"failure snapshot changed after bus recovered");
  $display("PASS SCCB live levels and retained failure snapshot");
  offset=rx_count; command("?"); response(offset,3,7);
  $display("ALL CAMERA TOP TESTS PASS"); $finish;
 end
 initial begin #50000000; $fatal(1,"simulation watchdog: state=%d cfgstate=%d sccbstate=%d",dut.state,dut.config_unit.state,dut.config_unit.bus.state); end
endmodule
