`default_nettype none
module ro_puf_top #(parameter integer CLEAR_CLOCKS=64, RELEASE_CLOCKS=32,
 WINDOW_CLOCKS=50000, DRAIN_CLOCKS=64, REPEAT_GAP=64)
 (input wire sysclk_50,rstn,output wire [4:0] led_n);
 reg [15:0] por_count=0;
 reg [31:0] clock_ticks=0;
 (* syn_preserve=1 *) reg [1:0] switch_sync=0;
 always @(posedge sysclk_50) begin
  if(!(&por_count)) por_count<=por_count+1'b1;
  clock_ticks<=clock_ticks+1'b1;
  switch_sync<={switch_sync[0],rstn};
 end
 wire resetn=&por_count;
 wire [31:0] control;
 reg [7:0] token=0,response=0,tie_mask=0,health=0;
 reg [15:0] challenge_index=0;
 reg busy=0,valid=0,bad_challenge=0,any_overflow=0;
 reg ro_enable=0,counter_clear=1;
 reg [31:0] timer=0;
 reg [2:0] lane_index=0,crc_index=0;
 reg [4:0] sample_index=0;
 reg [255:0] batch_data=0,batch_ties=0;
 reg [31:0] crc_response=32'hffffffff,crc_counts=32'hffffffff;
 reg [47:0] pair_snapshot=0;
 localparam IDLE=0,CLEAR=1,RELEASE=2,MEASURE=3,DRAIN=4,STORE=5,COUNT_CRC=6,SAMPLE=7,GAP=8;
 reg [3:0] state=IDLE;
 wire [4:0] select_a=challenge_index[4:0]+lane_index*3;
 wire [4:0] select_b=challenge_index[9:5]+lane_index*7;
 wire clock_a,clock_b;
 wire [23:0] count_a,count_b;
 wire overflow_a,overflow_b;
 ro_bank bank(.enable(ro_enable),.select_a(select_a),.select_b(select_b),.clock_a(clock_a),.clock_b(clock_b));
 ro_counter counter_a(.clock_in(clock_a),.clear(counter_clear),.count(count_a),.overflow(overflow_a));
 ro_counter counter_b(.clock_in(clock_b),.clear(counter_clear),.count(count_b),.overflow(overflow_b));

 // Single synchronous read port permits block RAM inference. Page readout is
 // frozen and acknowledged separately; each page carries four raw samples.
 reg [47:0] count_memory [0:255];
 reg [47:0] memory_word=0;
 reg [7:0] read_address=0;
 always @(posedge sysclk_50) begin
  if(busy && state==STORE) count_memory[{sample_index,lane_index}]<=pair_snapshot;
  memory_word<=count_memory[read_address];
 end
 reg [1535:0] count_page=0;
 reg [2:0] cached_page=0;
 reg [4:0] page_offset=0;
 reg [1:0] page_state=0;
 reg page_ready=0;
 wire [2:0] requested_page=control[18:16];
 always @(posedge sysclk_50) begin
  if(!resetn || busy || !valid) begin
   page_ready<=0; page_state<=0; page_offset<=0;
  end else case(page_state)
   0: if(!page_ready || requested_page!=cached_page) begin
       page_ready<=0; cached_page<=requested_page; page_offset<=0;
       read_address<={requested_page,5'b0}; page_state<=1;
      end
   1: page_state<=2;
   2: begin
       count_page[page_offset*48 +: 48]<=memory_word;
       if(page_offset==31) begin page_ready<=1; page_state<=0; end
       else begin page_offset<=page_offset+1'b1; read_address<=read_address+1'b1; page_state<=1; end
      end
  endcase
 end
 wire [63:0] status={16'h5258,challenge_index,token,valid,busy,health,response,bad_challenge,any_overflow,page_ready,1'b0,resetn,switch_sync[1]};
 wire [63:0] diagnostics={32'h524f4631,clock_ticks};
 wire [63:0] batch_info={16'h5231,8'd32,token,~crc_response};
 wire [63:0] count_info={16'h4341,token,page_ready,4'b0,cached_page,~crc_counts};
 assign led_n={~any_overflow,~busy,~valid,~switch_sync[1],~clock_ticks[24]};
 ro_dvio dvio(.clk(sysclk_50),.resetn(resetn),.control(control),.status(status),.diagnostics(diagnostics),
  .batch_data(batch_data),.batch_info(batch_info),.count_page(count_page),.count_info(count_info),.batch_ties(batch_ties));
 function [31:0] crc_byte;
 input [31:0] initial_crc;
 input [7:0] value;
 integer k;
 reg [31:0] crc;
 begin
  crc=initial_crc ^ {24'd0,value};
  for(k=0;k<8;k=k+1) crc=crc[0] ? (crc>>1)^32'hedb88320 : crc>>1;
  crc_byte=crc;
 end
 endfunction
 always @(posedge sysclk_50) begin
  if(!resetn) begin
   token<=0; response<=0; tie_mask<=0; health<=0; challenge_index<=0;
   busy<=0; valid<=0; bad_challenge<=0; any_overflow<=0;
   ro_enable<=0; counter_clear<=1; timer<=0; lane_index<=0; sample_index<=0;
   crc_index<=0; batch_data<=0; batch_ties<=0;
   crc_response<=32'hffffffff; crc_counts<=32'hffffffff; state<=IDLE;
  end else if(!busy && control[31:24]!=token && control[31:24]!=0) begin
   token<=control[31:24]; challenge_index<=control[15:0];
   response<=0; tie_mask<=0; batch_data<=0; batch_ties<=0;
   crc_response<=32'hffffffff; crc_counts<=32'hffffffff;
   timer<=0; lane_index<=0; sample_index<=0; ro_enable<=0; counter_clear<=1;
   any_overflow<=0; bad_challenge<=|control[15:10];
   if(|control[15:10]) begin valid<=1; busy<=0; health<=0; state<=IDLE; end
   else begin valid<=0; busy<=1; health<=8'hff; state<=CLEAR; end
  end else if(busy) begin
   timer<=timer+1'b1;
   case(state)
    CLEAR: if(timer==CLEAR_CLOCKS-1) begin counter_clear<=0; timer<=0; state<=RELEASE; end
    RELEASE: if(timer==RELEASE_CLOCKS-1) begin ro_enable<=1; timer<=0; state<=MEASURE; end
    MEASURE: if(timer==WINDOW_CLOCKS-1) begin ro_enable<=0; timer<=0; state<=DRAIN; end
    DRAIN: if(timer==DRAIN_CLOCKS-1) begin pair_snapshot<={count_b,count_a}; timer<=0; state<=STORE; end
    STORE: begin
      response[lane_index]<=pair_snapshot[23:0]>pair_snapshot[47:24];
      tie_mask[lane_index]<=pair_snapshot[23:0]==pair_snapshot[47:24];
      if(count_a==0 || count_b==0 || overflow_a || overflow_b) health[lane_index]<=0;
      any_overflow<=any_overflow | overflow_a | overflow_b;
      crc_index<=0; state<=COUNT_CRC;
     end
    COUNT_CRC: begin
      crc_counts<=crc_byte(crc_counts,pair_snapshot[crc_index*8 +: 8]);
      if(crc_index==5) begin
       if(lane_index==7) state<=SAMPLE;
       else begin lane_index<=lane_index+1'b1; timer<=0; counter_clear<=1; state<=CLEAR; end
      end else crc_index<=crc_index+1'b1;
     end
    SAMPLE: begin
      batch_data[sample_index*8 +: 8]<=response;
      batch_ties[sample_index*8 +: 8]<=tie_mask;
      crc_response<=crc_byte(crc_response,response);
      counter_clear<=1; timer<=0;
      if(sample_index==31) begin busy<=0; valid<=1; state<=IDLE; end
      else begin sample_index<=sample_index+1'b1; lane_index<=0; response<=0; tie_mask<=0; state<=GAP; end
     end
    GAP: if(timer==REPEAT_GAP-1) begin timer<=0; state<=CLEAR; end
    default: begin busy<=0; valid<=1; health<=0; ro_enable<=0; counter_clear<=1; end
   endcase
  end
 end
endmodule
`default_nettype wire
