`timescale 1ns/1ps
`default_nettype none
// KTR1 transport. Connect this 32-bit single-beat AXI master to a PA -> PU
// DDR port. No vendor hard-IP addresses/pins are guessed in this module.
// Frame RAM and metadata MUST remain immutable from frame_valid to frame_release.
// Metadata is latched by the camera producer at VSYNC, not by this DMA at send time.
module kosmo_training_transport #(
 parameter [31:0] DDR_BASE=32'h00300000,
 parameter integer FRAME_BYTES=38400,
 parameter integer CLOCK_HZ=50000000,
 parameter integer BUS_TIMEOUT_CYCLES=2500000
)(
 input wire clk, reset,
 input wire frame_valid,
 input wire [31:0] frame_sequence,
 input wire [63:0] frame_ticks,
 input wire [31:0] frame_command_sequence,
 input wire signed [31:0] frame_angle, frame_throttle,
 input wire [31:0] frame_flags, frame_dropped,
 output reg [15:0] frame_rd_addr,
 input wire [7:0] frame_rd_data, // synchronous RAM, one cycle read latency
 output reg frame_release,
 output reg control_valid,
 input wire control_ack, // core has accepted all setpoints; not mechanical feedback
 input wire [31:0] control_health,
 output reg [31:0] control_sequence, control_flags,
 output reg [31:0] control_steering,
 output reg signed [31:0] control_angle, control_throttle,
 output wire control_stop, // MUST independently override the actuator core
 output reg exposure_valid,output reg [31:0] exposure_setting,
 input wire exposure_done,input wire [1:0] exposure_status,
 input wire [31:0] exposure_applied,input wire exposure_allowed,
 output reg fault,
 output wire [8:0] debug_state,
 output reg [31:0] m_awaddr, output reg m_awvalid, input wire m_awready,
 output reg [31:0] m_wdata, output wire [3:0] m_wstrb,
 output reg m_wvalid, input wire m_wready,
 input wire [1:0] m_bresp, input wire m_bvalid, output reg m_bready,
 output reg [31:0] m_araddr, output reg m_arvalid, input wire m_arready,
 input wire [31:0] m_rdata, input wire [1:0] m_rresp,
 input wire m_rvalid, output reg m_rready
);
 localparam integer WATCHDOG_CYCLES=CLOCK_HZ*3/10;
 reg [31:0] watchdog;
 reg kick;
 assign control_stop=fault || watchdog>=WATCHDOG_CYCLES;
 assign m_wstrb=4'hf;
 always @(posedge clk) begin
  if(reset) watchdog<=WATCHDOG_CYCLES;
  else if(kick) watchdog<=0;
  else if(watchdog<WATCHDOG_CYCLES) watchdog<=watchdog+1;
 end

 // One transaction at a time. AW and W are independent; never require their
 // ready signals to coincide. A failed/stalled bus latches stop until reset.
 reg bus_read,bus_write,bus_done;
 reg [31:0] bus_addr,bus_data,read_data,bus_age;
 reg [2:0] bus_state;
 always @(posedge clk) begin
  if(reset) begin
   bus_state<=0;bus_done<=0;fault<=0;bus_age<=0;
   m_awvalid<=0;m_wvalid<=0;m_bready<=0;m_arvalid<=0;m_rready<=0;
   m_awaddr<=0;m_wdata<=0;m_araddr<=0;read_data<=0;
  end else begin
   bus_done<=0;
   if(bus_state!=0 && bus_state!=7) begin
    bus_age<=bus_age+1;
    if(bus_age>=BUS_TIMEOUT_CYCLES) begin fault<=1;bus_state<=7;end
   end
   case(bus_state)
    0:begin
     bus_age<=0;
     if(bus_write)begin m_awaddr<=bus_addr;m_wdata<=bus_data;m_awvalid<=1;m_wvalid<=1;bus_state<=1;end
     else if(bus_read)begin m_araddr<=bus_addr;m_arvalid<=1;bus_state<=3;end
    end
    1:begin
     if(m_awvalid&&m_awready)m_awvalid<=0;
     if(m_wvalid&&m_wready)m_wvalid<=0;
     if((!m_awvalid||m_awready)&&(!m_wvalid||m_wready))begin m_bready<=1;bus_state<=2;end
    end
    2:if(m_bvalid&&m_bready)begin
     m_bready<=0;
     if(m_bresp!=0)begin fault<=1;bus_state<=7;end
     else begin bus_done<=1;bus_state<=0;end
    end
    3:if(m_arvalid&&m_arready)begin m_arvalid<=0;m_rready<=1;bus_state<=4;end
    4:if(m_rvalid&&m_rready)begin
     m_rready<=0;
     if(m_rresp!=0)begin fault<=1;bus_state<=7;end
     else begin read_data<=m_rdata;bus_done<=1;bus_state<=0;end
    end
    7:begin m_awvalid<=0;m_wvalid<=0;m_bready<=0;m_arvalid<=0;m_rready<=0;end
   endcase
   // Timeout takes priority even if a handshake arrives on the final cycle.
   if(bus_state!=0&&bus_state!=7&&bus_age>=BUS_TIMEOUT_CYCLES)begin fault<=1;bus_state<=7;end
  end
 end

 localparam INIT=0, INIT_NEXT=1, MAGIC=2, POLL=3, CMD_SEQ=4,
  CMD_FLAGS=5,CMD_ANGLE=6,CMD_THROTTLE=7,CMD_TTL=8,CMD_VERIFY=9,
  CMD_WAIT=10,CMD_STATUS=11,CMD_ACK=12,FRAME_CHECK=13,FRAME_SLOT=14,
  PIXEL_WAIT=15,PIXEL_LATCH=16,PIXEL_NEXT=17,DESC=18,DESC_NEXT=19,
  PUBLISH=20,RELEASE=21,WAIT_BUS=22,POLL_COMMAND=23,CMD_STEERING=24,
  EXP_POLL=25,EXP_SEQ=26,EXP_SETTING=27,EXP_VERIFY=28,
  EXP_STATUS=29,EXP_APPLIED=30,EXP_ACK=31;
 reg [5:0] state,return_state;
 assign debug_state={bus_state,state};
 reg [5:0] init_index;
 reg [3:0] desc_index;
 reg [31:0] last_command,command_status,command_ttl,command_age;
 reg [31:0] published,pixel_word;
 reg [15:0] byte_index;
 reg [31:0] saved_seq,saved_command,saved_angle,saved_throttle,saved_flags,saved_dropped;
 reg [63:0] saved_ticks;
 reg exposure_pending,exposure_completed;
 reg [31:0] exposure_sequence,last_exposure,exposure_result,applied_exposure;
 task read_word;
  input [31:0] offset;
  input [5:0] next_state;
  begin bus_addr<=DDR_BASE+offset;bus_read<=1;return_state<=next_state;state<=WAIT_BUS;end
 endtask
 task write_word;
  input [31:0] offset,value;
  input [5:0] next_state;
  begin bus_addr<=DDR_BASE+offset;bus_data<=value;bus_write<=1;return_state<=next_state;state<=WAIT_BUS;end
 endtask
 always @(posedge clk)begin
  if(reset)begin
   state<=INIT;init_index<=0;bus_read<=0;bus_write<=0;bus_addr<=0;bus_data<=0;
   control_valid<=0;control_sequence<=0;control_flags<=0;control_angle<=0;control_throttle<=0;
   control_steering<=0;
   exposure_valid<=0;exposure_setting<=0;exposure_pending<=0;exposure_completed<=0;
   exposure_sequence<=0;last_exposure<=0;exposure_result<=0;applied_exposure<=0;
   frame_release<=0;frame_rd_addr<=0;kick<=0;published<=0;last_command<=0;
   byte_index<=0;pixel_word<=0;desc_index<=0;command_age<=0;command_status<=0;command_ttl<=0;
   saved_seq<=0;saved_ticks<=0;saved_command<=0;saved_angle<=0;saved_throttle<=0;saved_flags<=0;saved_dropped<=0;
   return_state<=INIT;
  end else begin
   bus_read<=0;bus_write<=0;frame_release<=0;kick<=0;
   // A camera SCCB operation must never block actuator heartbeat polling.
   if(exposure_pending&&exposure_done)begin
    exposure_valid<=0;exposure_completed<=1;
    exposure_result<={30'd0,exposure_status};applied_exposure<=exposure_applied;
   end
   if(fault)begin control_valid<=0;end
   else case(state)
    INIT:write_word({24'b0,init_index,2'b0},init_index==1?32'd3:32'd0,INIT_NEXT);
    INIT_NEXT:if(init_index==36)state<=MAGIC;else begin init_index<=init_index+1;state<=INIT;end
    MAGIC:write_word(0,32'h3152544b,POLL); // commit ABI only after initialization
    POLL:write_word('h34,control_health,POLL_COMMAND);
    POLL_COMMAND:read_word('h10,CMD_SEQ);
    CMD_SEQ:if(read_data!=last_command&&read_data!=0)begin control_sequence<=read_data;read_word('h14,CMD_FLAGS);end
            else state<=EXP_POLL;
    CMD_FLAGS:begin control_flags<=read_data;read_word('h18,CMD_ANGLE);end
    CMD_ANGLE:begin control_angle<=read_data;read_word('h1c,CMD_THROTTLE);end
    CMD_THROTTLE:begin control_throttle<=read_data;read_word('h20,CMD_TTL);end
    CMD_TTL:begin command_ttl<=read_data;read_word('h38,CMD_STEERING);end
    CMD_STEERING:begin control_steering<=read_data;read_word('h10,CMD_VERIFY);end
    CMD_VERIFY:begin
     if(read_data!=control_sequence)state<=POLL;
     else if(control_flags>3 || (control_flags[1]&&!control_flags[0]) ||
             (exposure_pending&&control_flags[0]) ||
             control_angle < -32'sd1000000 || control_angle > 32'sd1000000 ||
             control_throttle<0 || control_throttle>32'sd1000000 || command_ttl!=300 ||
             control_steering[31:28]!=0 || control_steering[15:12]!=0 ||
             control_steering[11:0]<462 || control_steering[11:0]>529 ||
             control_steering[27:16]<333 || control_steering[27:16]>396)begin
      command_status<=2;state<=CMD_STATUS;
     end else begin control_valid<=1;command_age<=0;state<=CMD_WAIT;end
    end
    CMD_WAIT:begin
     command_age<=command_age+1;
     if(control_ack)begin control_valid<=0;kick<=1;command_status<=1;state<=CMD_STATUS;end
     else if(command_age>=BUS_TIMEOUT_CYCLES)begin control_valid<=0;command_status<=2;state<=CMD_STATUS;end
    end
    CMD_STATUS:write_word('h28,command_status,CMD_ACK);
    CMD_ACK:begin last_command<=control_sequence;write_word('h24,control_sequence,EXP_POLL);end
    EXP_POLL:if(exposure_pending)begin
     if(exposure_completed)state<=EXP_STATUS;else state<=FRAME_CHECK;
    end else read_word('h80,EXP_SEQ);
    EXP_SEQ:if(read_data!=0&&read_data!=last_exposure)begin
     exposure_sequence<=read_data;read_word('h84,EXP_SETTING);
    end else state<=FRAME_CHECK;
    EXP_SETTING:begin exposure_setting<=read_data;read_word('h80,EXP_VERIFY);end
    EXP_VERIFY:if(read_data!=exposure_sequence)state<=FRAME_CHECK;
    else if(exposure_setting[30:11]!=0||exposure_setting[10:0]>1200||!exposure_allowed||control_flags[0])begin
     exposure_result<=2;state<=EXP_STATUS;
    end else begin exposure_valid<=1;exposure_pending<=1;exposure_completed<=0;state<=FRAME_CHECK;end
    EXP_STATUS:write_word('h8c,exposure_result,EXP_APPLIED);
    EXP_APPLIED:write_word('h90,applied_exposure,EXP_ACK);
    EXP_ACK:begin
     last_exposure<=exposure_sequence;exposure_pending<=0;exposure_completed<=0;
     write_word('h88,exposure_sequence,FRAME_CHECK);
    end
    FRAME_CHECK:if(frame_valid)read_word('h2c,FRAME_SLOT);else state<=POLL;
    FRAME_SLOT:if(read_data!=published)state<=POLL;else begin
     saved_seq<=frame_sequence;saved_ticks<=frame_ticks;saved_command<=frame_command_sequence;
     saved_angle<=frame_angle;saved_throttle<=frame_throttle;saved_flags<=frame_flags;saved_dropped<=frame_dropped;
     byte_index<=0;frame_rd_addr<=0;pixel_word<=0;state<=PIXEL_WAIT;
    end
    PIXEL_WAIT:state<=PIXEL_LATCH;
    PIXEL_LATCH:begin
     case(byte_index[1:0])
      0:pixel_word[7:0]<=frame_rd_data;
      1:pixel_word[15:8]<=frame_rd_data;
      2:pixel_word[23:16]<=frame_rd_data;
      3:pixel_word[31:24]<=frame_rd_data;
     endcase
     state<=PIXEL_NEXT;
    end
    PIXEL_NEXT:if(byte_index[1:0]==3)begin
     write_word('h1000+{16'b0,byte_index[15:2],2'b0},pixel_word,byte_index==FRAME_BYTES-1?DESC:PIXEL_WAIT);
     if(byte_index==FRAME_BYTES-1)desc_index<=0;
     byte_index<=byte_index+1;frame_rd_addr<=byte_index+1;
    end else begin byte_index<=byte_index+1;frame_rd_addr<=byte_index+1;state<=PIXEL_WAIT;end
    DESC:case(desc_index)
     0:write_word('h40,saved_seq,DESC_NEXT);
     1:write_word('h44,FRAME_BYTES,DESC_NEXT);
     2:write_word('h48,saved_ticks[31:0],DESC_NEXT);
     3:write_word('h4c,saved_ticks[63:32],DESC_NEXT);
     4:write_word('h50,saved_command,DESC_NEXT);
     5:write_word('h54,saved_angle,DESC_NEXT);
     6:write_word('h58,saved_throttle,DESC_NEXT);
     7:write_word('h5c,saved_flags,DESC_NEXT);
     8:write_word('h60,saved_dropped,DESC_NEXT);
    endcase
    DESC_NEXT:if(desc_index==8)state<=PUBLISH;else begin desc_index<=desc_index+1;state<=DESC;end
    PUBLISH:write_word('h30,saved_seq,RELEASE);
    RELEASE:begin published<=saved_seq;frame_release<=1;state<=POLL;end
    WAIT_BUS:if(bus_done)state<=return_state;
   endcase
  end
 end
endmodule
`default_nettype wire
