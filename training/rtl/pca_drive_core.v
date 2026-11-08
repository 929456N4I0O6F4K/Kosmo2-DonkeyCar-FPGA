`timescale 1ns/1ps
`default_nettype none
// Persistent control at nominal 60 Hz. Reset verifies all-off.
// ESC neutral is 380 ticks; v5 extends forward full-scale to 441 (~1800 us).
// Disabled host heartbeats establish neutral and arm once, before driving.
// Normal stops keep neutral PWM alive; only independent stop/fault goes all-off.
module pca_drive_core #(
 parameter integer CLOCK_HZ=50000000,BUS_HZ=100000,
 parameter integer ARM_CYCLES=250000000,RETURN_CYCLES=50000000,
 parameter integer RETRY_CYCLES=5000000
)(
 input wire clk,reset,stop,
 input wire command_valid,input wire [31:0] command_sequence,command_flags,
 input wire signed [31:0] command_angle,command_throttle,
 input wire [31:0] command_steering, // {4'b0,right_ticks[11:0],4'b0,left_ticks[11:0]}
 output reg command_ack,
 output reg [31:0] applied_sequence,applied_flags,
 output reg signed [31:0] applied_angle,applied_throttle,
 inout wire scl,sda,
 output reg ready,fault,active,armed,shutdown_unconfirmed,
 output wire [63:0] diagnostics
);
 localparam ISSUE=0,WAIT=1,WARM=2,IDLE=3,RETRY=4,MAP=5;
 localparam INIT=0,OFF=1,UPDATE=2,RETURN=3,VERIFY=4;
 localparam [11:0] ESC_NEUTRAL_TICKS=12'd380,ESC_FORWARD_MAX_TICKS=12'd441;
 localparam [6:0] ESC_FORWARD_SPAN=ESC_FORWARD_MAX_TICKS-ESC_NEUTRAL_TICKS;
 reg [2:0] state,operation;reg [5:0] step;
 reg start,read_en;reg [7:0] address,value,expected,mask;
 reg write_pair;reg [7:0] value_hi;
 wire busy,done;wire [1:0] error;wire [7:0] result;
 wire [15:0] live,failure;reg [15:0] first_failure;
 reg [31:0] timer,delay_count,last_seen,accepted_flags,accepted_sequence;
 reg signed [31:0] accepted_angle,accepted_throttle;
 reg [11:0] steer_ticks,esc_ticks;
 reg returning,seen_valid,pending_ack;
 wire [31:0] angle_magnitude=command_angle<0 ? -command_angle : command_angle;
 wire [6:0] steering_span=command_angle<0 ? command_steering[11:0]-12'd428 : 12'd428-command_steering[27:16];
 wire [26:0] steering_product=angle_magnitude*steering_span;
 wire [26:0] throttle_product=command_throttle*ESC_FORWARD_SPAN;
 reg [26:0] steering_remainder,throttle_remainder;
 reg map_left;
 wire new_command=command_valid&&(!seen_valid||command_sequence!=last_seen);
 wire valid_range=command_flags<=3 && !(command_flags[1]&&!command_flags[0]) &&
                   command_angle>=-32'sd1000000&&command_angle<=32'sd1000000&&
                   command_throttle>=0&&command_throttle<=32'sd1000000&&
                   command_steering[31:28]==0&&command_steering[15:12]==0&&
                   command_steering[11:0]>=462&&command_steering[11:0]<=529&&
                   command_steering[27:16]>=333&&command_steering[27:16]<=396;
 assign diagnostics={first_failure,live,esc_ticks,steer_ticks,3'd0,shutdown_unconfirmed,armed,active,fault,ready};
 pca_i2c #(.CLOCK_HZ(CLOCK_HZ),.BUS_HZ(BUS_HZ),.PAIR_SUPPORT(1)) bus(
 .clk(clk),.rst(reset),.start(start),.read_en(read_en),.reg_addr(address),.write_data(value),
 .write_pair(write_pair),.write_data_hi(value_hi),
 .busy(busy),.done(done),.error(error),.read_data(result),.scl(scl),.sda(sda),.debug_live(live),.debug_failure(failure));
 always @*begin
  address=8'hfd;value=8'h10;read_en=0;expected=0;mask=0;
  write_pair=0;value_hi=0;
  if(operation==INIT)case(step)
   0:begin end
   1:begin address=0;value=8'h30;end
   2:begin address=1;value=4;end
   3:begin address=8'hfe;value=101;end
   4:begin address=0;value=8'h20;end
   5:begin read_en=1;address=0;expected=8'h20;mask=8'h7f;end
   6:begin read_en=1;address=1;expected=4;mask=8'h1f;end
   7:begin read_en=1;address=8'hfe;expected=101;mask=8'hff;end
   default:begin read_en=1;address=8'h09+((step-8)<<2);expected=8'h10;mask=8'h10;end
  endcase
  else if(operation==OFF)begin
   if(step!=0)begin read_en=1;address=8'h09+((step-1)<<2);expected=8'h10;mask=8'h10;end
  end else if(operation==VERIFY)begin
   // A PCA power cycle can restore default frequency/all-off without a host
   // reset. Never keep reporting an armed standby without reading the device.
   read_en=1;
   case(step)
    0:begin address=0;expected=8'h20;mask=8'h7f;end
    1:begin address=1;expected=4;mask=8'h1f;end
    2:begin address=8'hfe;expected=101;mask=8'hff;end
    3:begin address=8'h06;expected=0;mask=8'hff;end
    4:begin address=8'h07;expected=0;mask=8'h1f;end
    5:begin address=8'h08;expected=esc_ticks[7:0];mask=8'hff;end
    6:begin address=8'h09;expected=1;mask=8'h1f;end
    7:begin address=8'h12;expected=0;mask=8'hff;end
    8:begin address=8'h13;expected=0;mask=8'h1f;end
    9:begin address=8'h14;expected=steer_ticks[7:0];mask=8'hff;end
    10:begin address=8'h15;expected={4'd0,steer_ticks[11:8]};mask=8'h1f;end
   endcase
  end else case(step)
   // ESC widths stay below 512; extended steering can cross into OFF_H=2.
   0:begin address=8'h06;value=0;end
   1:begin address=8'h07;value=0;end
   // AI=1 and OCH=0: latch both width bytes at the same I2C STOP.
   2:begin address=8'h08;value=esc_ticks[7:0];write_pair=1;value_hi=1;end
   3:begin read_en=1;address=8'h09;expected=1;mask=8'h1f;end
   4:begin read_en=1;address=8'h08;expected=esc_ticks[7:0];mask=255;end
   5:begin read_en=1;address=8'h09;expected=1;mask=8'h1f;end
   6:begin address=8'h12;value=0;end
   7:begin address=8'h13;value=0;end
   8:begin address=8'h14;value=steer_ticks[7:0];write_pair=1;value_hi={4'd0,steer_ticks[11:8]};end
   9:begin read_en=1;address=8'h15;expected={4'd0,steer_ticks[11:8]};mask=8'h1f;end
   10:begin read_en=1;address=8'h14;expected=steer_ticks[7:0];mask=255;end
   11:begin read_en=1;address=8'h15;expected={4'd0,steer_ticks[11:8]};mask=8'h1f;end
   12:begin read_en=1;address=0;expected=8'h20;mask=8'h7f;end
   13:begin read_en=1;address=1;expected=4;mask=8'h1f;end
   14:begin read_en=1;address=8'hfe;expected=101;mask=8'hff;end
  endcase
 end
 task begin_stop;
  begin
   applied_flags<=0;applied_angle<=0;applied_throttle<=0;armed<=0;pending_ack<=0;
   esc_ticks<=ESC_NEUTRAL_TICKS;steer_ticks<=428;step<=0;state<=ISSUE;operation<=RETURN;
   returning<=1;shutdown_unconfirmed<=1;
  end
 endtask
 always @(posedge clk)begin
  start<=0;command_ack<=0;
  if(reset)begin
   state<=ISSUE;operation<=INIT;step<=0;start<=0;ready<=0;fault<=0;active<=0;armed<=0;
   shutdown_unconfirmed<=1;first_failure<=0;timer<=0;delay_count<=0;returning<=0;
   applied_sequence<=0;applied_flags<=0;applied_angle<=0;applied_throttle<=0;
   last_seen<=0;seen_valid<=0;pending_ack<=0;accepted_sequence<=0;accepted_flags<=0;
   accepted_angle<=0;accepted_throttle<=0;esc_ticks<=ESC_NEUTRAL_TICKS;steer_ticks<=428;
   steering_remainder<=0;throttle_remainder<=0;map_left<=0;
  end else begin
   if(active && timer<ARM_CYCLES)timer<=timer+1;
   if(active&&!returning&&!fault&&timer>=ARM_CYCLES)armed<=1;
   case(state)
    ISSUE:begin
     if(stop&&active&&!returning&&!fault&&operation==UPDATE)begin_stop;
     else if(!busy)begin start<=1;state<=WAIT;end
    end
    WAIT:if(done)begin
     if(error!=0 || (read_en&&((result&mask)!=(expected&mask))))begin
      if(!fault)first_failure<=error!=0?failure:16'hffff;
      fault<=1;ready<=0;armed<=0;applied_flags<=0;applied_angle<=0;applied_throttle<=0;
      pending_ack<=0;shutdown_unconfirmed<=1;operation<=OFF;step<=0;delay_count<=0;state<=RETRY;
     end else if(stop&&active&&!returning&&!fault&&operation==UPDATE)begin_stop;
     else if(operation==INIT&&step==4)begin delay_count<=0;state<=WARM;end
     else if((operation==INIT&&step==23)||(operation==OFF&&step==16)||(operation==VERIFY&&step==10)||((operation==UPDATE||operation==RETURN)&&step==14))begin
      state<=IDLE;
      if(operation==INIT)begin ready<=1;shutdown_unconfirmed<=0;end
      else if(operation==OFF)begin active<=0;returning<=0;shutdown_unconfirmed<=0;end
      else if(operation==VERIFY)begin
       applied_sequence<=accepted_sequence;
       if(pending_ack)begin command_ack<=1;pending_ack<=0;end
      end
      else if(operation==RETURN)begin
       timer<=0;
       if(pending_ack)begin command_ack<=1;pending_ack<=0;applied_sequence<=accepted_sequence;end
      end
      else begin
       if(!active)begin active<=1;timer<=0;end
       applied_sequence<=accepted_sequence;applied_flags<=accepted_flags;
       applied_angle<=accepted_angle;applied_throttle<=accepted_throttle;
       if(pending_ack)begin command_ack<=1;pending_ack<=0;end
      end
     end else begin step<=step+1;state<=ISSUE;end
    end
    WARM:if(delay_count>=CLOCK_HZ/1000)begin step<=5;state<=ISSUE;end else delay_count<=delay_count+1;
    RETRY:if(delay_count>=RETRY_CYCLES)begin state<=ISSUE;delay_count<=0;end else delay_count<=delay_count+1;
    // Exact integer division with a bounded 101-cycle conversion. Avoids a
    // large combinational divider on the 50 MHz control path.
    MAP:begin
     if(stop)begin
      if(active)begin_stop;
      else begin pending_ack<=0;state<=IDLE;end
     end else if(steering_remainder<1000000&&throttle_remainder<1000000)state<=ISSUE;
     else begin
      if(steering_remainder>=1000000)begin
       steering_remainder<=steering_remainder-1000000;
       steer_ticks<=map_left?steer_ticks+1:steer_ticks-1;
      end
      if(throttle_remainder>=1000000)begin
       throttle_remainder<=throttle_remainder-1000000;esc_ticks<=esc_ticks+1;
      end
     end
    end
    IDLE:begin
     if(active&&!returning&&(stop||fault))begin_stop;
     else if(returning&&timer>=RETURN_CYCLES)begin operation<=OFF;step<=0;state<=ISSUE;end
     else if(new_command)begin
      last_seen<=command_sequence;seen_valid<=1;
      if(!valid_range)begin fault<=1;ready<=0;if(active)begin_stop;end
      else if(!command_flags[0])begin
       if(ready&&!fault&&!stop&&!returning&&(!active||applied_flags[0]))begin
        // Establish neutral during service startup, or stop an ordinary drive.
        // Preserve the arming timer and PWM across subsequent drive gestures.
        accepted_sequence<=command_sequence;accepted_flags<=0;
        accepted_angle<=0;accepted_throttle<=0;esc_ticks<=ESC_NEUTRAL_TICKS;steer_ticks<=428;
        pending_ack<=1;operation<=UPDATE;step<=0;state<=ISSUE;
       end else if(ready&&!fault&&!stop&&!returning&&active)begin
        accepted_sequence<=command_sequence;pending_ack<=1;
        operation<=VERIFY;step<=0;state<=ISSUE;
       end else if(returning||!shutdown_unconfirmed)begin
        applied_sequence<=command_sequence;applied_flags<=0;command_ack<=1;
       end
      end else if(ready&&!fault&&!stop&&!returning)begin
       accepted_sequence<=command_sequence;accepted_flags<=command_flags;
       accepted_angle<=armed?command_angle:0;accepted_throttle<=armed?command_throttle:0;
       steer_ticks<=428;esc_ticks<=ESC_NEUTRAL_TICKS;
       // Round to the nearest available PWM tick so small steering inputs
       // are symmetric about center, rather than truncating toward neutral.
       steering_remainder<=armed?steering_product+27'd500000:0;
       throttle_remainder<=armed?throttle_product+27'd500000:0;
       map_left<=command_angle<0;
       pending_ack<=1;operation<=UPDATE;step<=0;state<=MAP;
      end
     end
    end
   endcase
  end
 end
endmodule
`default_nettype wire
