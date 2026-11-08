`timescale 1ns/1ps
// Deterministic clocks test the controller/counter, never silicon PUF quality.
module GTP_DFF_C #(parameter GRS_EN="TRUE",parameter INIT=0)
 (input wire CLK,D,C,output reg Q=INIT);
 always @(posedge CLK or posedge C) if(C) Q<=0; else Q<=D;
endmodule
module ro_bank(input wire enable,input wire [4:0] select_a,select_b,output reg clock_a=1,clock_b=1);
 always begin #(2.0+select_a%5); if(enable) clock_a=~clock_a; else clock_a=1; end
 always begin #(2.0+select_b%5); if(enable) clock_b=~clock_b; else clock_b=1; end
endmodule
module ro_dvio(input wire clk,resetn,input wire [63:0] status,diagnostics,batch_info,count_info,
 input wire [255:0] batch_data,batch_ties,input wire [1535:0] count_page,output wire [31:0] control);
 reg [31:0] command=0;
 assign control=command;
endmodule
module tb_control;
 reg clk=0,rstn=0;
 always #10 clk=~clk;
 wire [4:0] led;
 ro_puf_top #(.CLEAR_CLOCKS(4),.RELEASE_CLOCKS(3),.WINDOW_CLOCKS(20),.DRAIN_CLOCKS(4),.REPEAT_GAP(3))
  dut(.sysclk_50(clk),.rstn(rstn),.led_n(led));
 reg fast_clock=0,test_clear=1;
 always #2 fast_clock=~fast_clock;
 wire [1:0] tiny_count;
 wire tiny_overflow;
 ro_counter #(.WIDTH(2)) tiny(.clock_in(fast_clock),.clear(test_clear),.count(tiny_count),.overflow(tiny_overflow));
 integer frames,counts;
 task clocks;
 input integer n;
 integer i;
 begin for(i=0;i<n;i=i+1) begin @(posedge clk); #1; end end
 endtask
 task measure;
 input [7:0] tok;
 input [15:0] index;
 integer b,k,page,j,steps;
 reg [1535:0] expected;
 begin
  for(b=0;b<16;b=b+1) begin
   @(negedge clk); dut.dvio.command[b]=index[b]; clocks(2);
   if(dut.busy) $fatal(1,"payload-only update triggered measurement");
  end
  @(negedge clk); dut.dvio.command[31:24]=tok;
  clocks(3);
  if(!dut.busy || dut.valid || dut.ro_enable) $fatal(1,"missing clear/release interval");
  steps=0;
  while(dut.busy && steps<20000) begin clocks(1); steps=steps+1; end
  if(!dut.valid || dut.busy || dut.health!=8'hff || dut.any_overflow) $fatal(1,"RO batch failed");
  if(dut.challenge_index!=index || dut.token!=tok) $fatal(1,"challenge/token mismatch");
  $fdisplay(frames,"%016h %064h %08h %08h %064h",dut.status,dut.batch_data,~dut.crc_response,~dut.crc_counts,dut.batch_ties);
  for(k=0;k<256;k=k+1) $fdisplay(counts,"%012h",dut.count_memory[k]);
  for(page=0;page<8;page=page+1) begin
   @(negedge clk); dut.dvio.command[18:16]=page;
   clocks(80);
   if(!dut.page_ready || dut.cached_page!=page || dut.busy) $fatal(1,"page acknowledgement missing");
   for(j=0;j<32;j=j+1) expected[j*48 +: 48]=dut.count_memory[page*32+j];
   if(dut.count_page!==expected) $fatal(1,"synchronous RAM page order incorrect");
   if(dut.count_info[47:40]!=tok || dut.count_info[39:32]!=(8'h80|page)) $fatal(1,"page metadata wrong");
  end
 end
 endtask
 initial begin
  frames=$fopen("frames.hex","w"); counts=$fopen("counts.hex","w");
  clocks(2); test_clear=0;
  clocks(65540);
  if(!tiny_overflow || tiny_count!=3) $fatal(1,"counter failed to saturate/flag overflow");
  if(!dut.resetn || dut.status[1:0]!=2'b10) $fatal(1,"C20 held experiment reset");
  measure(1,0);
  rstn=1; clocks(4);
  measure(129,1023);
  @(negedge clk); dut.dvio.command={8'd129,8'd0,16'd42};
  clocks(100);
  if(dut.busy || dut.challenge_index!=1023) $fatal(1,"same token retriggered batch");
  @(negedge clk); dut.dvio.command={8'd1,8'd0,16'd1024};
  clocks(4);
  if(!dut.valid || !dut.bad_challenge || dut.health!=0 || dut.ro_enable || dut.busy) $fatal(1,"out-of-range challenge accepted");
  $fclose(frames); $fclose(counts);
  $display("PASS RO control: C20-independent startup, sequential lanes, counter saturation, 32 raw samples, eight RAM pages, token and index validation");
  $finish;
 end
 initial begin #10000000; $fatal(1,"test timeout"); end
endmodule
