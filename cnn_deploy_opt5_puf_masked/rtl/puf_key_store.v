`timescale 1ns/1ps
`default_nettype none
// Board key copied from a block ROM after every reset. Capture and production
// images use the same RTL and constraints and differ only in puf_key.mem, so
// one placed-and-routed implementation serves both; only DRM init data changes.
// Words 0-7: binding relation, 8-15: stability mask (18 bits each, least
// significant word first), 16: mode, 17-31: fixed filler so that no ROM output
// bit is constant whatever key is loaded. tools/puf_key_image.py writes it.
// Any mode word other than the two codes below keeps the drive stopped.
module puf_key_store #(parameter KEY_FILE = "puf_key.mem") (
    input wire clk, rst,
    input wire [143:0] signs,
    output reg loaded,
    output wire capture_enable, drive_enable,
    // A stable bit that differs from the enrolled relation negates its dense
    // MAC tap. All zero outside production mode, which preserves opt4 exactly.
    output wire [143:0] mismatch
);
    localparam [17:0] MODE_CAPTURE = 18'h2C0D0, MODE_DRIVE = 18'h1D0E0;
    (* rom_style="block", syn_romstyle="block_rom" *) reg [17:0] key_rom [0:31];
    initial $readmemh(KEY_FILE, key_rom);
    reg [4:0] step;       // ROM address; q holds word step-1
    reg [17:0] q, mode;
    reg [143:0] binding, sign_mask;
    always @(posedge clk) q <= key_rom[step];
    always @(posedge clk) begin
        if (rst) begin
            step <= 0; loaded <= 0; mode <= 0; binding <= 0; sign_mask <= 0;
        end else if (!loaded) begin
            step <= step + 1'b1;
            if (step >= 5'd1 && step <= 5'd8) binding <= {q, binding[143:18]};
            if (step >= 5'd9 && step <= 5'd16) sign_mask <= {q, sign_mask[143:18]};
            if (step == 5'd17) begin mode <= q; loaded <= 1; end
        end
    end
    assign capture_enable = loaded && mode == MODE_CAPTURE;
    assign drive_enable = loaded && mode == MODE_DRIVE;
    assign mismatch = drive_enable ? sign_mask & (signs ^ binding) : 144'd0;
endmodule
`default_nettype wire
