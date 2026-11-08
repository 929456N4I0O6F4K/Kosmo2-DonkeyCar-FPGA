`timescale 1ns/1ps
`default_nettype none
module camera_config #(parameter integer CLOCK_HZ=50000000, BUS_HZ=100000,
 parameter integer SCL_PUSH_PULL=0, RUNTIME_EXPOSURE=0)(
 input wire clk, rst, colorbar, output reg cam_reset_n,
 output reg ready, failed, id_ok, output reg [7:0] pid, ver,
 output reg [7:0] error_code, output reg [8:0] config_index,
 inout wire scl, sda, output wire [39:0] debug_sccb,
 input wire exposure_valid,input wire [31:0] exposure_setting,
 output wire exposure_done,output wire [1:0] exposure_status,
 output wire [31:0] exposure_applied
);
 localparam POWER=0, WAIT_BOOT=1, ISSUE=2, WAIT_BUS=3, WAIT_DELAY=4, FINISH=5;
 reg [2:0] state;
 reg [2:0] phase;
 reg [31:0] timer;
 reg start;
 wire busy, bus_done;
 wire [1:0] bus_error;
 wire [7:0] read_data, rom_addr, rom_data, rom_delay;
 wire rom_last;
 wire read_en=(phase==1 || phase==2);
 wire [7:0] addr=(phase==0)?8'hff:(phase==1)?8'h0a:(phase==2)?8'h0b:rom_addr;
 wire [7:0] data=(phase==0)?8'h01:rom_data;
 wire runtime_select=RUNTIME_EXPOSURE&&ready;
 wire runtime_start,runtime_read;
 wire [7:0] runtime_address,runtime_data;
 wire [15:0] debug_live, debug_failure;
 assign debug_sccb={1'b0,state,cam_reset_n,phase,debug_failure,debug_live};
 camera_sccb #(.CLOCK_HZ(CLOCK_HZ),.BUS_HZ(BUS_HZ),.SCL_PUSH_PULL(SCL_PUSH_PULL)) bus(
  .clk(clk),.rst(rst),.start(runtime_select?runtime_start:start),
  .read_en(runtime_select?runtime_read:read_en),
  .reg_addr(runtime_select?runtime_address:addr),.write_data(runtime_select?runtime_data:data),
  .busy(busy),.done(bus_done),.error(bus_error),.read_data(read_data),.scl(scl),.sda(sda),
  .debug_live(debug_live),.debug_failure(debug_failure));
 generate if(RUNTIME_EXPOSURE)begin:runtime_control
  camera_exposure #(.CLOCK_HZ(CLOCK_HZ)) exposure(
   .clk(clk),.reset(rst),.enable(ready&&!failed),.valid(exposure_valid),.setting(exposure_setting),
   .done(exposure_done),.status(exposure_status),.applied(exposure_applied),
   .start(runtime_start),.read_en(runtime_read),.address(runtime_address),.data(runtime_data),
   .bus_busy(busy),.bus_done(bus_done),.bus_error(bus_error),.read_data(read_data));
 end else begin:no_runtime_control
  assign runtime_start=0;assign runtime_read=0;assign runtime_address=0;assign runtime_data=0;
  assign exposure_done=0;assign exposure_status=0;assign exposure_applied=0;
 end endgenerate
 ov2640_init_rom rom(.index(config_index),.colorbar(colorbar),.reg_addr(rom_addr),
  .reg_data(rom_data),.delay_ms(rom_delay),.last(rom_last));
 always @(posedge clk) begin
  start<=0;
  if (rst) begin
   state<=POWER; phase<=0; timer<=0; cam_reset_n<=0;
   ready<=0; failed<=0; id_ok<=0; pid<=0; ver<=0; error_code<=0; config_index<=0;
  end else case(state)
   POWER: if (timer>=CLOCK_HZ/200-1) begin
    cam_reset_n<=1; timer<=0; state<=WAIT_BOOT;
   end else timer<=timer+1'b1;
   WAIT_BOOT: if (timer>=CLOCK_HZ/20-1) begin timer<=0; state<=ISSUE; end
              else timer<=timer+1'b1;
   ISSUE: if (!busy) begin
    if (phase==3 && rom_last) begin ready<=1; state<=FINISH; end
    else begin start<=1; state<=WAIT_BUS; end
   end
   WAIT_BUS: if (bus_done) begin
    if (bus_error!=0) begin
     failed<=1; error_code<={6'd0,bus_error}; state<=FINISH;
    end else if (phase==0) begin phase<=1; state<=ISSUE; end
    else if (phase==1) begin pid<=read_data; phase<=2; state<=ISSUE; end
    else if (phase==2) begin
     ver<=read_data;
     if (pid==8'h26 && (read_data==8'h42 || read_data==8'h41)) begin
      id_ok<=1; phase<=3; state<=ISSUE;
     end else begin failed<=1; error_code<=3; state<=FINISH; end
    end else begin
     timer<=rom_delay*(CLOCK_HZ/1000); config_index<=config_index+1'b1;
     state<=WAIT_DELAY;
    end
   end
   WAIT_DELAY: if (timer==0) state<=ISSUE; else timer<=timer-1'b1;
   FINISH: if(RUNTIME_EXPOSURE&&exposure_done&&exposure_status==3)failed<=1;
   default: state<=POWER;
  endcase
 end
endmodule
`default_nettype wire
