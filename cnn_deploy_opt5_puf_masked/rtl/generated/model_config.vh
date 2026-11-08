// Generated for 95x156 model.
localparam signed [31:0] STEERING_ZP = -20;
localparam signed [31:0] STEERING_SCALE_Q30 = 9633795;
localparam signed [31:0] THROTTLE_ZP = -20;
localparam signed [31:0] THROTTLE_SCALE_Q30 = 9633795;
always @* begin
    cfg_taps=0; cfg_row_span=0; cfg_row_skip=0; cfg_stride_x=0; cfg_stride_y=0;
    cfg_out_h=0; cfg_out_w=0; cfg_out_c=0; cfg_ring_bytes=0;
    case(tail_stage)
        3'd2: begin
            cfg_taps=800;
            cfg_row_span=160;
            cfg_row_skip=992;
            cfg_stride_x=64;
            cfg_stride_y=2304;
            cfg_out_h=9;
            cfg_out_w=16;
            cfg_out_c=64;
            cfg_ring_bytes=6912;
        end
        3'd3: begin
            cfg_taps=576;
            cfg_row_span=192;
            cfg_row_skip=832;
            cfg_stride_x=64;
            cfg_stride_y=1024;
            cfg_out_h=7;
            cfg_out_w=14;
            cfg_out_c=64;
        end
        3'd4: begin
            cfg_taps=576;
            cfg_row_span=192;
            cfg_row_skip=704;
            cfg_stride_x=64;
            cfg_stride_y=896;
            cfg_out_h=5;
            cfg_out_w=12;
            cfg_out_c=16;
        end
        3'd5: begin
            cfg_taps=960;
            cfg_row_span=960;
            cfg_row_skip=0;
            cfg_stride_x=0;
            cfg_stride_y=0;
            cfg_out_h=1;
            cfg_out_w=1;
            cfg_out_c=100;
        end
        3'd6: begin
            cfg_taps=100;
            cfg_row_span=100;
            cfg_row_skip=0;
            cfg_stride_x=0;
            cfg_stride_y=0;
            cfg_out_h=1;
            cfg_out_w=1;
            cfg_out_c=50;
        end
        3'd7: begin
            cfg_taps=50;
            cfg_row_span=50;
            cfg_row_skip=0;
            cfg_stride_x=0;
            cfg_stride_y=0;
            cfg_out_h=1;
            cfg_out_w=1;
            cfg_out_c=2;
        end
    endcase
end
