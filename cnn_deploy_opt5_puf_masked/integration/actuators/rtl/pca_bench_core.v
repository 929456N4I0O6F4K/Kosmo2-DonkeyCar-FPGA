`timescale 1ns/1ps
`default_nettype none
// Bench only: steering pulse or timed ESC neutral/test/neutral sequence.
// I2C shutdown cannot stop an independently powered PCA if the bus breaks.
module pca_bench_core #(
 parameter integer CLOCK_HZ=50000000, BUS_HZ=100000,
 parameter integer PULSE_CYCLES=100000000,
 parameter integer RETRY_CYCLES=5000000,
 parameter integer ESC_ARM_CYCLES=250000000,
 parameter integer ESC_TEST_CYCLES=25000000,
 parameter integer ESC_RETURN_CYCLES=50000000
)(input wire clk, resetn, input wire [31:0] control,
 inout wire scl,sda, output wire [63:0] status,diagnostics);
 localparam IDLE=0, ISSUE=1, WAIT_BUS=2, WARM=3, RETRY=4;
 localparam OFF=1, INIT=2, READ=3, PULSE=4, ESC_NEUTRAL=5, ESC_TRIAL=6, ESC_HOLD=7,
            JOINT_STEER=8, JOINT_DRIVE=9, JOINT_WRITE=10, JOINT_CENTER=11;
 reg [2:0] state;
 reg [3:0] operation,last_op,error,channel;
 reg [5:0] step;
 reg [7:0] token,requested_reg,result;
 reg [11:0] ticks;
 reg [11:0] esc_neutral,esc_target;
 reg [11:0] joint_ticks,joint_target,joint_center;
 reg [1:0] esc_phase;
 reg esc_neutral_valid;
 reg pwm_60hz;
 reg ready,active,shutdown_pending,expired;
 reg [31:0] timer,delay_count;
 reg [31:0] esc_test_cycles;
 (* syn_preserve=1 *) reg [31:0] control_meta,control_sync;
 reg [31:0] control_prev;
 reg start;
 reg bus_read;
 reg [7:0] bus_reg,bus_data,expected,mask;
 wire bus_busy,bus_done;
 wire [1:0] bus_error;
 wire [7:0] bus_result;
 wire [15:0] live,failure;
 reg [15:0] failure_latched;
 wire [7:0] base=8'h06+{2'b00,channel,2'b00};
 wire command_new=(control_sync==control_prev && control_sync[31:24]!=token);
 wire [7:0] pwm_prescale=pwm_60hz ? 8'd101 : 8'd121;
 // Preserve nominal microsecond limits when changing the shared PWM period.
 wire [11:0] pulse_min=pwm_60hz ? 12'd294 : 12'd246;
 wire [11:0] pulse_max=pwm_60hz ? 12'd441 : 12'd369;
 wire [11:0] steering_max=pwm_60hz ? 12'd634 : 12'd530;
 wire [11:0] neutral_min=pwm_60hz ? 12'd343 : 12'd287;
 wire [11:0] neutral_max=pwm_60hz ? 12'd392 : 12'd328;
 wire [11:0] throttle_min=pwm_60hz ? 12'd306 : 12'd256;
 wire [31:0] hold_cycles=esc_phase==1 ? ESC_ARM_CYCLES :
                         esc_phase==2 ? esc_test_cycles :
                         esc_phase==3 ? ESC_RETURN_CYCLES : PULSE_CYCLES;
 wire joint_sequence=(last_op==JOINT_STEER || last_op==JOINT_DRIVE);
 wire esc_sequence=(last_op==ESC_TRIAL || last_op==ESC_HOLD || joint_sequence);
 wire [7:0] displayed_result=(last_op==ESC_NEUTRAL || esc_sequence) ? {6'b0,esc_phase} : result;
 assign status={16'h5043,8'h09,token,last_op,error,displayed_result,requested_reg,
                1'b0,live[5],live[6],expired,shutdown_pending,(state!=IDLE),active,ready};
 assign diagnostics={timer,failure_latched,live};
 pca_i2c #(.CLOCK_HZ(CLOCK_HZ),.BUS_HZ(BUS_HZ)) bus(
  .clk(clk),.rst(!resetn),.start(start),.read_en(bus_read),
  .reg_addr(bus_reg),.write_data(bus_data),.busy(bus_busy),.done(bus_done),
  .error(bus_error),.read_data(bus_result),.scl(scl),.sda(sda),
  .debug_live(live),.debug_failure(failure));
 // Transaction table. The four ALL_LED_* locations are write-only (read zero).
 // Shutdown is verified through all sixteen individual OFF_H registers.
 always @* begin
  bus_reg=8'hfd; bus_data=8'h10; bus_read=0; expected=0; mask=0;
  case(operation)
   OFF: if(step!=0) begin
    bus_read=1; bus_reg=8'h09+((step-1'b1)<<2); expected=8'h10; mask=8'h10;
   end
   INIT: case(step)
    0: begin end
    1: begin bus_reg=0; bus_data=8'h10; end
    2: begin bus_reg=1; bus_data=8'h04; end
    3: begin bus_reg=8'hfe; bus_data=pwm_prescale; end
    4: begin bus_reg=0; bus_data=0; end
    5: begin bus_read=1; bus_reg=0; expected=0; mask=8'h7f; end
    6: begin bus_read=1; bus_reg=1; expected=4; mask=8'h1f; end
    7: begin bus_read=1; bus_reg=8'hfe; expected=pwm_prescale; mask=8'hff; end
    default: begin
     bus_read=1; bus_reg=8'h09+((step-6'd8)<<2); expected=8'h10; mask=8'h10;
    end
   endcase
   READ: begin bus_read=1; bus_reg=requested_reg; end
   PULSE: case(step)
    0: begin end
    1: begin bus_reg=base; bus_data=0; end
    2: begin bus_reg=base+1'b1; bus_data=0; end
    3: begin bus_reg=base+2'd2; bus_data=ticks[7:0]; end
    4: begin bus_reg=base+2'd3; bus_data={4'b0,ticks[11:8]}; end
    5: begin bus_read=1; bus_reg=base; mask=8'hff; end
    6: begin bus_read=1; bus_reg=base+1'b1; mask=8'h1f; end
    7: begin bus_read=1; bus_reg=base+2'd2; expected=ticks[7:0]; mask=8'hff; end
    8: begin bus_read=1; bus_reg=base+2'd3; expected={4'b0,ticks[11:8]}; mask=8'h1f; end
   endcase
   // Joint phases keep both channels enabled. All allowed widths have OFF_H=1,
   // so only OFF_L changes width; there is no full-off gap between phases.
   // ESC is updated first, including return to neutral before centering steering.
   JOINT_WRITE: case(step)
    0: begin end
    1: begin bus_reg=8'h06; bus_data=0; end
    2: begin bus_reg=8'h07; bus_data=0; end
    3: begin bus_reg=8'h08; bus_data=ticks[7:0]; end
    4: begin bus_reg=8'h09; bus_data=8'h01; end
    5: begin bus_read=1; bus_reg=8'h06; mask=8'hff; end
    6: begin bus_read=1; bus_reg=8'h07; mask=8'h1f; end
    7: begin bus_read=1; bus_reg=8'h08; expected=ticks[7:0]; mask=8'hff; end
    8: begin bus_read=1; bus_reg=8'h09; expected=1; mask=8'h1f; end
    9: begin bus_reg=8'h12; bus_data=0; end
    10: begin bus_reg=8'h13; bus_data=0; end
    11: begin bus_reg=8'h14; bus_data=joint_ticks[7:0]; end
    12: begin bus_reg=8'h15; bus_data=8'h01; end
    13: begin bus_read=1; bus_reg=8'h12; mask=8'hff; end
    14: begin bus_read=1; bus_reg=8'h13; mask=8'h1f; end
    15: begin bus_read=1; bus_reg=8'h14; expected=joint_ticks[7:0]; mask=8'hff; end
    16: begin bus_read=1; bus_reg=8'h15; expected=1; mask=8'h1f; end
   endcase
  endcase
 end
 always @(posedge clk) begin
  control_meta<=control; control_sync<=control_meta; control_prev<=control_sync;
  start<=0;
  if(!resetn) begin
   control_meta<=0; control_sync<=0; control_prev<=0;
   state<=ISSUE; operation<=OFF; last_op<=0; step<=0; token<=0;
   error<=0; channel<=0; ticks<=0; requested_reg<=0; result<=0;
   esc_neutral<=307; esc_target<=307; esc_phase<=0; esc_neutral_valid<=0;
   joint_ticks<=415; joint_target<=415; joint_center<=415;
   esc_test_cycles<=ESC_TEST_CYCLES;
   pwm_60hz<=0;
   ready<=0; active<=0; shutdown_pending<=1; expired<=0;
   timer<=0; delay_count<=0; start<=0; failure_latched<=0;
  end else begin
   if(active && timer<hold_cycles) timer<=timer+1'b1;
   case(state)
    IDLE: begin
     if(command_new && control_sync[23:20]==OFF) begin
      token<=control_sync[31:24]; last_op<=OFF;
      if(active) esc_neutral_valid<=0;
      esc_phase<=0; operation<=OFF; step<=0; shutdown_pending<=1; state<=ISSUE;
     end else if(active && timer>=hold_cycles) begin
      if(esc_sequence && esc_phase==1) begin
       esc_phase<=2; ticks<=esc_target; joint_ticks<=joint_target;
       operation<=joint_sequence ? JOINT_WRITE : PULSE; step<=3; state<=ISSUE;
      end else if(esc_sequence && esc_phase==2) begin
       esc_phase<=3; ticks<=esc_neutral; joint_ticks<=joint_center;
       operation<=joint_sequence ? JOINT_WRITE : PULSE; step<=3; state<=ISSUE;
      end else begin
       if(last_op==ESC_NEUTRAL && esc_phase==1) esc_neutral_valid<=1;
       esc_phase<=0; expired<=1; shutdown_pending<=1; operation<=OFF; step<=0; state<=ISSUE;
      end
     end else if(command_new) begin
      token<=control_sync[31:24]; last_op<=control_sync[23:20];
      if(control_sync[23:20]==OFF) begin
       operation<=OFF; step<=0; shutdown_pending<=1; state<=ISSUE;
      end else if(active) begin
       // No extension/retrigger of a running pulse, even with a fresh token.
       error<=3; ready<=0; esc_phase<=0; esc_neutral_valid<=0;
       operation<=OFF; step<=0; shutdown_pending<=1; state<=ISSUE;
      end else if(control_sync[23:20]==INIT &&
                  (control_sync[15:0]==0 || control_sync[15:0]==50 || control_sync[15:0]==60)) begin
       ready<=0; error<=0; expired<=0; failure_latched<=0;
       pwm_60hz<=control_sync[15:0]==60;
       joint_center<=415;
       esc_neutral_valid<=0; esc_phase<=0;
       operation<=INIT; step<=0; state<=ISSUE;
      end else if(control_sync[23:20]==READ &&
                   (control_sync[15:0]<=16'h45 || control_sync[15:0]==16'hfe)) begin
       requested_reg<=control_sync[7:0]; operation<=READ; step<=0; state<=ISSUE;
      end else if(control_sync[23:20]==PULSE && ready && error==0 &&
                   control_sync[19:16]!=0 &&
                   control_sync[15:0]>=pulse_min &&
                   (control_sync[15:0]<=pulse_max ||
                    (control_sync[19:16]==3 && control_sync[15:0]<=steering_max))) begin
       channel<=control_sync[19:16]; ticks<=control_sync[11:0];
       esc_phase<=0; expired<=0; operation<=PULSE; step<=0; state<=ISSUE;
      end else if(control_sync[23:20]==ESC_NEUTRAL && ready && error==0 &&
                  control_sync[19:16]==0 && control_sync[15:0]>=neutral_min && control_sync[15:0]<=neutral_max) begin
       channel<=0; ticks<=control_sync[11:0]; esc_neutral<=control_sync[11:0];
       esc_neutral_valid<=0; esc_phase<=1; expired<=0;
       operation<=PULSE; step<=0; state<=ISSUE;
      end else if(control_sync[23:20]==ESC_TRIAL && ready && error==0 && esc_neutral_valid &&
                  control_sync[19:16]==0 && control_sync[15:0]>=throttle_min && control_sync[15:0]<=pulse_max) begin
      channel<=0; ticks<=esc_neutral; esc_target<=control_sync[11:0];
       esc_test_cycles<=ESC_TEST_CYCLES;
       esc_phase<=1; expired<=0; operation<=PULSE; step<=0; state<=ISSUE;
      end else if(control_sync[23:20]==ESC_HOLD && ready && error==0 && esc_neutral_valid &&
                  control_sync[19:16]==0 && pwm_60hz && esc_neutral==380 &&
                  control_sync[11:0]==406 &&
                  (control_sync[15:12]==1 || control_sync[15:12]==2 || control_sync[15:12]==5)) begin
       // New timed mode is restricted to the user-reproduced 1550/1655 us pair.
       // Duration is latched at command acceptance; fresh commands cannot extend it.
       channel<=0; ticks<=esc_neutral; esc_target<=406;
       case(control_sync[15:12])
        1: esc_test_cycles<=ESC_TEST_CYCLES*2;
        2: esc_test_cycles<=ESC_TEST_CYCLES*4;
        5: esc_test_cycles<=ESC_TEST_CYCLES*10;
       endcase
       esc_phase<=1; expired<=0; operation<=PULSE; step<=0; state<=ISSUE;
      end else if(control_sync[23:20]==JOINT_CENTER && ready && error==0 && pwm_60hz &&
                  control_sync[19:16]==3 && control_sync[15:0]>=404 && control_sync[15:0]<=429) begin
       // Idle-only center configuration (1650..1750 us); no PCA writes or PWM.
       // The high byte is always 1. Echo the low byte in the result for host checking.
       joint_center<=control_sync[11:0]; result<=control_sync[7:0]; esc_phase<=0;
      end else if((control_sync[23:20]==JOINT_STEER || control_sync[23:20]==JOINT_DRIVE) &&
                  ready && error==0 && esc_neutral_valid && pwm_60hz && esc_neutral==380 &&
                  control_sync[19:16]==0 &&
                  control_sync[11:0]>=355 && control_sync[11:0]<=500 &&
                  ((control_sync[23:20]==JOINT_STEER && control_sync[15:12]==2) ||
                   (control_sync[23:20]==JOINT_DRIVE && control_sync[15:12]<=2))) begin
       // Fixed 1550/1655 us ESC pair, bounded 1450..2040 us steering, at most 2 s.
       // All steering widths stay within OFF_H=1, preserving gapless updates.
       channel<=0; ticks<=380; joint_ticks<=joint_center; joint_target<=control_sync[11:0];
       esc_target<=control_sync[23:20]==JOINT_DRIVE ? 406 : 380;
       case(control_sync[15:12])
        0: esc_test_cycles<=ESC_TEST_CYCLES;
        1: esc_test_cycles<=ESC_TEST_CYCLES*2;
        2: esc_test_cycles<=ESC_TEST_CYCLES*4;
       endcase
       esc_phase<=1; expired<=0; operation<=JOINT_WRITE; step<=0; state<=ISSUE;
      end else begin
       error<= ((control_sync[23:20]==PULSE || control_sync[23:20]==ESC_NEUTRAL ||
                 control_sync[23:20]==ESC_TRIAL || control_sync[23:20]==ESC_HOLD ||
                 control_sync[23:20]==JOINT_STEER || control_sync[23:20]==JOINT_DRIVE ||
                 control_sync[23:20]==JOINT_CENTER) && !ready) ||
                ((control_sync[23:20]==ESC_TRIAL || control_sync[23:20]==ESC_HOLD ||
                  control_sync[23:20]==JOINT_STEER || control_sync[23:20]==JOINT_DRIVE) && !esc_neutral_valid) ? 4 : 3;
      end
     end
    end
    ISSUE: if(!bus_busy && !start) begin
     start<=1; state<=WAIT_BUS;
     // Start expiry before the first possibly enabled PWM write.
     // ESC range 256..369 (50 Hz) / 306..441 (60 Hz) keeps OFF_H=1.
     // Only the low byte changes pulse width; no full-off gap or byte rollover.
     if((operation==PULSE || operation==JOINT_WRITE) &&
        ((step==4 && esc_phase<2) || (step==3 && esc_phase>=2))) begin
      active<=1; timer<=0;
     end
    end
    WAIT_BUS: if(bus_done) begin
     if(bus_error!=0 || (bus_read && ((bus_result & mask)!=(expected & mask)))) begin
      error<=bus_error!=0 ? {2'b00,bus_error} : 5;
      // Preserve the first bus failure until INIT; retries must not erase it.
      if(failure_latched==0) failure_latched<=failure;
      ready<=0; shutdown_pending<=1;
      esc_phase<=0; esc_neutral_valid<=0;
      operation<=OFF; step<=0; delay_count<=0; state<=RETRY;
     end else if(operation==OFF && step==16) begin
      active<=0; shutdown_pending<=0; state<=IDLE;
     end else if(operation==INIT && step==23) begin
      ready<=1; shutdown_pending<=0; state<=IDLE;
     end else if(operation==READ) begin
      result<=bus_result; state<=IDLE;
     end else if(operation==PULSE && step==8) state<=IDLE;
     else if(operation==JOINT_WRITE && step==16) state<=IDLE;
     else if(operation==INIT && step==4) begin
      delay_count<=0; step<=5; state<=WARM;
     end else begin step<=step+1'b1; state<=ISSUE; end
    end
    WARM: if(delay_count>=CLOCK_HZ/1000) state<=ISSUE;
          else delay_count<=delay_count+1'b1;
    RETRY: if(delay_count>=RETRY_CYCLES) state<=ISSUE;
           else delay_count<=delay_count+1'b1;
    default: begin
     ready<=0; esc_phase<=0; esc_neutral_valid<=0;
     shutdown_pending<=1; operation<=OFF; step<=0; state<=ISSUE;
    end
   endcase
  end
 end
endmodule
`default_nettype wire
