`timescale 1ns/1ps
module tb_training_transport;
 reg clk=0;always #10 clk=~clk;
 reg reset=1;
 reg frame_valid=0;reg [31:0] frame_sequence=1;
 wire [15:0] frame_rd_addr;reg [7:0] frame_rd_data;
 always @(posedge clk)frame_rd_data<=frame_rd_addr[7:0];
 wire frame_release,control_valid,control_stop,fault;
 reg control_ack=0;reg allow_control=1;
 always @(posedge clk)control_ack<=control_valid&&allow_control;
 wire [31:0] control_sequence,control_flags,control_angle,control_throttle;
 wire [31:0] control_steering;
 reg [31:0] steering=32'h016701f6;
 wire exposure_valid;wire [31:0] exposure_setting;
 reg exposure_done=0,exposure_allowed=1;reg [1:0] exposure_status=1;
 reg [31:0] exposure_applied=0;integer exposure_delay=0,exposure_count=0;
 always @(posedge clk)begin
  exposure_done<=0;
  if(reset)begin exposure_delay<=0;exposure_count<=0;end
  else if(exposure_valid&&exposure_delay==0)begin exposure_delay<=1;exposure_count<=exposure_count+1;end
  else if(exposure_delay>0&&exposure_delay<2000)exposure_delay<=exposure_delay+1;
  else if(exposure_delay==2000)begin exposure_done<=1;exposure_applied<=exposure_setting;exposure_delay<=2001;end
  else if(!exposure_valid)exposure_delay<=0;
 end
 wire [31:0] awaddr,wdata,araddr;wire [3:0] wstrb;
 wire awvalid,wvalid,bready,arvalid,rready;
 reg awready=0,wready=0,bvalid=0,arready=0,rvalid=0;
 reg [1:0] bresp=0,rresp=0;reg [31:0] rdata=0;
 reg [31:0] mem[0:16383];reg [31:0] pending_addr,pending_data;
 reg got_aw=0,got_w=0;integer cycles=0;reg stall_bus=0;reg inject_error=0;
 integer i;
 kosmo_training_transport #(.FRAME_BYTES(16),.CLOCK_HZ(10000),.BUS_TIMEOUT_CYCLES(200)) dut(
 .clk(clk),.reset(reset),.frame_valid(frame_valid),.frame_sequence(frame_sequence),
 .frame_ticks(64'd500000),.frame_command_sequence(32'd7),.frame_angle(-32'sd250000),.frame_throttle(32'd120000),.frame_flags(32'd3),.frame_dropped(32'd2),
 .frame_rd_addr(frame_rd_addr),.frame_rd_data(frame_rd_data),.frame_release(frame_release),
 .control_valid(control_valid),.control_ack(control_ack),.control_sequence(control_sequence),.control_flags(control_flags),.control_angle(control_angle),.control_throttle(control_throttle),.control_stop(control_stop),.fault(fault),
 .control_steering(control_steering),.control_health(32'd0),
 .exposure_valid(exposure_valid),.exposure_setting(exposure_setting),.exposure_done(exposure_done),
 .exposure_status(exposure_status),.exposure_applied(exposure_applied),.exposure_allowed(exposure_allowed),
 .m_awaddr(awaddr),.m_awvalid(awvalid),.m_awready(awready),.m_wdata(wdata),.m_wstrb(wstrb),.m_wvalid(wvalid),.m_wready(wready),.m_bresp(bresp),.m_bvalid(bvalid),.m_bready(bready),
 .m_araddr(araddr),.m_arvalid(arvalid),.m_arready(arready),.m_rdata(rdata),.m_rresp(rresp),.m_rvalid(rvalid),.m_rready(rready));
 always @(posedge clk)begin
  cycles<=cycles+1;
  // AW and W deliberately never ready in the same cycle.
  awready<=!stall_bus && cycles%4==0 && !got_aw;
  wready<=!stall_bus && cycles%4==2 && !got_w;
  arready<=!stall_bus && cycles%3==0 && !rvalid;
  if(reset)begin got_aw<=0;got_w<=0;bvalid<=0;rvalid<=0;end
  else begin
   if(awvalid&&awready)begin pending_addr<=awaddr;got_aw<=1;end
   if(wvalid&&wready)begin pending_data<=wdata;got_w<=1;end
   if(got_aw&&got_w&&!bvalid)begin
    if(wstrb!=15)$fatal(1,"bad strobes");
    mem[(pending_addr-32'h00300000)>>2]<=pending_data;
    bvalid<=1;bresp<=inject_error?2:0;
   end
   if(bvalid&&bready)begin bvalid<=0;got_aw<=0;got_w<=0;end
   if(arvalid&&arready)begin rdata<=mem[(araddr-32'h00300000)>>2];rvalid<=1;end
   if(rvalid&&rready)rvalid<=0;
  end
 end
 task command;
  input [31:0] seq,flags,angle,throttle;
  begin
   @(negedge clk);mem['h14/4]=flags;mem['h18/4]=angle;mem['h1c/4]=throttle;mem['h20/4]=300;
   mem['h38/4]=steering;
   mem['h10/4]=seq;
   wait(mem['h24/4]==seq);@(negedge clk);
  end
 endtask
 task restart;
  begin reset=1;repeat(5)@(negedge clk);reset=0;wait(mem[0]==0);wait(mem[0]==32'h3152544b);repeat(10)@(negedge clk);end
 endtask
 initial begin
  for(i=0;i<16384;i=i+1)mem[i]=0;
  restart;
  if(mem[1]!=3)$fatal(1,"exposure ABI version missing");
  if(!control_stop)$fatal(1,"startup stop missing");
  command(1,3,-32'sd250000,32'd120000);
  if(mem['h28/4]!=1||control_stop||control_angle!=-32'sd250000)$fatal(1,"command not applied");
  if(control_steering!=steering)$fatal(1,"steering payload not latched with command");
  frame_valid=1;wait(frame_release);@(negedge clk);frame_valid=0;
  if(mem['h30/4]!=1||mem['h40/4]!=1||mem['h44/4]!=16)$fatal(1,"publish metadata");
  if(mem['h1000/4]!=32'h03020100||mem['h100c/4]!=32'h0f0e0d0c)$fatal(1,"byte order/RAM latency");
  if(mem['h50/4]!=7||mem['h54/4]!=-32'sd250000||mem['h58/4]!=120000||mem['h5c/4]!=3)$fatal(1,"frame labels changed");
  frame_sequence=2;frame_valid=1;repeat(300)@(negedge clk);
  if(mem['h30/4]!=1||frame_release)$fatal(1,"owned slot overwritten");
  command(2,1,0,0);if(mem['h24/4]!=2)$fatal(1,"full frame slot blocked control");
  @(negedge clk);mem['h2c/4]=1;
  wait(frame_release);@(negedge clk);frame_valid=0;
  if(mem['h30/4]!=2)$fatal(1,"slot not reused after consumer release");
  command(3,3,0,32'd1000001);if(mem['h28/4]!=2)$fatal(1,"invalid throttle accepted");
  repeat(3100)@(negedge clk);if(!control_stop)$fatal(1,"watchdog missing");
  command(4,0,0,0);if(mem['h28/4]!=1)$fatal(1,"disable not acknowledged");
  allow_control=0;command(5,1,0,0);if(mem['h28/4]!=2)$fatal(1,"control ACK timeout ignored");
  allow_control=1;
  steering=32'h01670212;command(6,1,0,0);
  if(mem['h28/4]!=2)$fatal(1,"invalid steering left endpoint accepted");
  steering=32'h014c01f6;command(7,1,0,0);
  if(mem['h28/4]!=2)$fatal(1,"invalid steering right endpoint accepted");
  steering=32'h116701f6;command(8,1,0,0);
  if(mem['h28/4]!=2)$fatal(1,"reserved steering bits accepted");
  steering=32'h016701f6;
  command(9,0,0,0);
  @(negedge clk);mem['h84/4]=300;mem['h80/4]=1;
  wait(exposure_valid);
  command(10,0,0,0);if(mem['h28/4]!=1)$fatal(1,"exposure blocked neutral heartbeat");
  command(11,1,0,0);if(mem['h28/4]!=2)$fatal(1,"driving enabled while exposure busy");
  wait(mem['h88/4]==1);
  if(mem['h8c/4]!=1||mem['h90/4]!=300||exposure_count!=1)$fatal(1,"exposure ACK/applied mismatch");
  @(negedge clk);mem['h84/4]=1201;mem['h80/4]=2;
  wait(mem['h88/4]==2);if(mem['h8c/4]!=2||exposure_count!=1)$fatal(1,"invalid exposure touched hardware");
  exposure_allowed=0;
  @(negedge clk);mem['h84/4]=300;mem['h80/4]=3;
  wait(mem['h88/4]==3);if(mem['h8c/4]!=2||exposure_count!=1)$fatal(1,"active labels accepted exposure");
  exposure_allowed=1;
  command(12,0,0,0);
  inject_error=1;command(13,0,0,0);
 end
 initial begin
  wait(inject_error);wait(fault);if(!control_stop)$fatal(1,"AXI error did not stop");
  $display("PASS transport: byte order, stable labels, ownership, independent AXI handshakes, command ACK, invalid command, watchdog, bus error");
  inject_error=0;frame_valid=0;restart;
  stall_bus=1;repeat(250)@(negedge clk);if(!fault||!control_stop)$fatal(1,"stalled AXI did not stop");
  $display("ALL TRAINING TRANSPORT TESTS PASS");$finish;
 end
 initial begin #5000000;$fatal(1,"test timeout");end
endmodule
