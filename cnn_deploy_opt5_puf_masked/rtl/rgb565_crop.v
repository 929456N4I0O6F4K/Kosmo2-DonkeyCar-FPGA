`timescale 1ns/1ps
`default_nettype none
// Read a frozen 160x120 MSB-first RGB565 byte RAM, one-cycle read latency.
// Retain y=25..119, x=2..157. Replicate low bits exactly as training/uio_linux.go.
// Write NHWC RGB signed int8 bytes (pixel XOR 0x80), without resize or padding.
module rgb565_crop (
    input wire clk, rst, start,
    output wire idle,
    output reg done,
    output wire raw_ce,
    output wire [15:0] raw_address,
    input wire [7:0] raw_q,
    output wire write_valid,
    output reg [16:0] write_address,
    output wire [7:0] write_q
);
    localparam IDLE=0, READ_HI=1, READ_LO=2, EMIT_R=3, EMIT_G=4, EMIT_B=5;
    reg [2:0] state;
    reg [7:0] high_byte;
    reg [7:0] col, row;
    reg [15:0] pixel_address;
    wire [4:0] red = high_byte[7:3];
    wire [5:0] green = {high_byte[2:0],raw_q[7:5]};
    wire [4:0] blue = raw_q[4:0];
    wire [7:0] rgb = state==EMIT_R ? {red,red[4:2]} :
                     state==EMIT_G ? {green,green[5:4]} : {blue,blue[4:2]};
    assign idle=state==IDLE;
    assign raw_ce=state==READ_HI || state==READ_LO;
    assign raw_address=pixel_address + (state==READ_LO ? 16'd1 : 16'd0);
    assign write_valid=state==EMIT_R || state==EMIT_G || state==EMIT_B;
    assign write_q=rgb ^ 8'h80;
    always @(posedge clk) begin
        if(rst) begin state<=IDLE; done<=0; write_address<=0;
            pixel_address<=0; col<=0; row<=0; high_byte<=0; end
        else begin
            done<=0;
            if(write_valid) write_address<=write_address+1'b1;
            case(state)
                IDLE: if(start) begin
                    state<=READ_HI; row<=25; col<=2;
                    pixel_address<=16'd8004; write_address<=0;
                end
                READ_HI: state<=READ_LO;
                READ_LO: begin high_byte<=raw_q; state<=EMIT_R; end
                EMIT_R: state<=EMIT_G;
                EMIT_G: state<=EMIT_B;
                EMIT_B: begin
                    if(col==157) begin
                        col<=2; row<=row+1'b1; pixel_address<=pixel_address+16'd10;
                        if(row==119) begin state<=IDLE; done<=1; end
                        else state<=READ_HI;
                    end else begin
                        col<=col+1'b1; pixel_address<=pixel_address+16'd2; state<=READ_HI;
                    end
                end
                default: state<=IDLE;
            endcase
        end
    end
endmodule
`default_nettype wire
