`timescale 1ns/1ps
module camera_jtag_top(
 input wire sysclk_50,rstn,uart_rx,
 output wire uart_tx, output wire [4:0] led_n,
 input wire cam_pclk,cam_vsync,cam_href, input wire [7:0] cam_data,
 output wire cam_reset_n, inout wire cam_scl,cam_sda
);
 // Bench profile with internal weak pullups: give the bus longer to rise.
 camera_top #(.ENABLE_JTAG(1),.SCCB_HZ(10000)) camera(
  .sysclk_50(sysclk_50),.rstn(rstn),.uart_rx(uart_rx),.uart_tx(uart_tx),.led_n(led_n),
  .cam_pclk(cam_pclk),.cam_vsync(cam_vsync),.cam_href(cam_href),.cam_data(cam_data),
  .cam_reset_n(cam_reset_n),.cam_scl(cam_scl),.cam_sda(cam_sda));
endmodule
