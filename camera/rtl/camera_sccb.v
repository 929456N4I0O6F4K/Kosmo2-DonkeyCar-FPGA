`timescale 1ns/1ps
`default_nettype none
// OV2640: 7-bit SCCB address 0x30; STOP between subaddress and read.
// SDA is open drain. SCL defaults to open drain; the OV2640-only host can
// select push-pull SCL because the sensor's SIO_C pin is an input.
// Open-drain wires require pull-ups. Push-pull SCL has no clock stretching.
module camera_sccb #(parameter integer CLOCK_HZ=50000000, BUS_HZ=100000,
 parameter integer SCL_PUSH_PULL=0)(
 input wire clk, rst, start, read_en,
 input wire [7:0] reg_addr, write_data,
 output reg busy, done, output reg [1:0] error,
 output reg [7:0] read_data, inout wire scl, sda,
 output wire [15:0] debug_live, output reg [15:0] debug_failure
);
 localparam integer QUARTER=CLOCK_HZ/(4*BUS_HZ);
 localparam IDLE=0, START_A=1, START_B=2, START_C=3,
 BIT_SET=4, BIT_UP=5, BIT_HOLD=6, BIT_DOWN=7,
 ACK_SET=8, ACK_UP=9, ACK_SAMPLE=10, ACK_DOWN=11,
 READ_SET=12, READ_UP=13, READ_SAMPLE=14, READ_DOWN=15,
 NACK_SET=16, NACK_UP=17, NACK_HOLD=18, NACK_DOWN=19,
 STOP_LOW=20, STOP_UP=21, STOP_RELEASE=22, STOP_DONE=23;
 reg [4:0] state;
 reg scl_low, sda_low, do_read, read_phase, read_restart;
 reg [7:0] addr, data, shift;
 reg [2:0] bit_no;
 reg [1:0] byte_no;
 reg [15:0] divider;
 reg [31:0] watchdog;
 (* syn_preserve=1 *) reg [1:0] scl_sync, sda_sync;
 // Bits 4:0 state, 5 SDA in, 6 SCL in, 7 SDA drive-low, 8 SCL drive-low,
 // 9 busy, 11:10 error, 12 read phase, 14:13 byte index, 15 done.
 assign debug_live={done,byte_no,read_phase,error,busy,scl_low,sda_low,scl_sync[1],sda_sync[1],state};
 assign scl=scl_low ? 1'b0 : (SCL_PUSH_PULL ? 1'b1 : 1'bz);
 assign sda=sda_low ? 1'b0 : 1'bz;
 always @(posedge clk) begin
  scl_sync <= {scl_sync[0],scl}; sda_sync <= {sda_sync[0],sda}; done <= 0;
  if (rst) begin
   state<=IDLE; busy<=0; done<=0; error<=0; read_data<=0;
   scl_low<=0; sda_low<=0; divider<=0; watchdog<=0;
   do_read<=0; read_phase<=0; read_restart<=0;
   addr<=0; data<=0; shift<=0; byte_no<=0; bit_no<=0;
   scl_sync<=3; sda_sync<=3;
   debug_failure<=0;
  end else if (!busy) begin
   divider<=0; watchdog<=0;
   if (start) begin
    busy<=1; error<=0; read_data<=0;
    addr<=reg_addr; data<=write_data; do_read<=read_en;
    read_phase<=0; read_restart<=0; byte_no<=0;
    shift<=8'h60; bit_no<=7; state<=START_A;
    debug_failure<=0;
   end
  end else if (watchdog >= CLOCK_HZ/100) begin
   busy<=0; done<=1; error<=2; state<=IDLE; scl_low<=0; sda_low<=0;
   debug_failure<=debug_live;
  end else begin
   watchdog<=watchdog+1'b1;
   if (divider != QUARTER-1) divider<=divider+1'b1;
   else begin
    divider<=0;
    case (state)
     START_A: begin scl_low<=0; sda_low<=0; if (scl_sync[1] && sda_sync[1]) state<=START_B; end
     START_B: begin sda_low<=1; state<=START_C; end
     START_C: begin scl_low<=1; state<=BIT_SET; end
     BIT_SET: begin sda_low<=!shift[bit_no]; state<=BIT_UP; end
     BIT_UP: begin scl_low<=0; state<=BIT_HOLD; end
     BIT_HOLD: if (scl_sync[1]) state<=BIT_DOWN;
     BIT_DOWN: begin
      scl_low<=1;
      if (bit_no==0) state<=ACK_SET;
      else begin bit_no<=bit_no-1'b1; state<=BIT_SET; end
     end
     ACK_SET: begin sda_low<=0; state<=ACK_UP; end
     ACK_UP: begin scl_low<=0; state<=ACK_SAMPLE; end
     ACK_SAMPLE: if (scl_sync[1]) begin
      if (sda_sync[1]) begin error<=1; debug_failure<=debug_live; end
      state<=ACK_DOWN;
     end
     ACK_DOWN: begin
      scl_low<=1; bit_no<=7;
      if (error!=0) begin read_restart<=0; state<=STOP_LOW; end
      else if (read_phase) state<=READ_SET;
      else if (byte_no==0) begin shift<=addr; byte_no<=1; state<=BIT_SET; end
      else if (byte_no==1 && do_read) begin read_restart<=1; state<=STOP_LOW; end
      else if (byte_no==1) begin shift<=data; byte_no<=2; state<=BIT_SET; end
      else state<=STOP_LOW;
     end
     READ_SET: begin sda_low<=0; state<=READ_UP; end
     READ_UP: begin scl_low<=0; state<=READ_SAMPLE; end
     READ_SAMPLE: if (scl_sync[1]) begin read_data[bit_no]<=sda_sync[1]; state<=READ_DOWN; end
     READ_DOWN: begin
      scl_low<=1;
      if (bit_no==0) state<=NACK_SET;
      else begin bit_no<=bit_no-1'b1; state<=READ_SET; end
     end
     NACK_SET: begin sda_low<=0; state<=NACK_UP; end
     NACK_UP: begin scl_low<=0; state<=NACK_HOLD; end
     NACK_HOLD: if (scl_sync[1]) state<=NACK_DOWN;
     NACK_DOWN: begin scl_low<=1; state<=STOP_LOW; end
     STOP_LOW: begin scl_low<=1; sda_low<=1; state<=STOP_UP; end
     STOP_UP: begin scl_low<=0; state<=STOP_RELEASE; end
     STOP_RELEASE: if (scl_sync[1]) begin sda_low<=0; state<=STOP_DONE; end
     STOP_DONE: begin
      if (read_restart) begin
       read_restart<=0; read_phase<=1; shift<=8'h61; bit_no<=7; state<=START_A;
      end else begin busy<=0; done<=1; state<=IDLE; end
     end
     default: begin
      state<=IDLE; busy<=0; error<=2; done<=1; scl_low<=0; sda_low<=0;
      debug_failure<=debug_live;
     end
    endcase
   end
  end
 end
endmodule
`default_nettype wire

