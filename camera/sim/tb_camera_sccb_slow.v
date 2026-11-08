`timescale 1ns/1ps
// 50 MHz system / 10 kHz bus with an artificial 8 us rising-edge delay.
// This exercises slow-rise protocol tolerance; it is not an analog RC model.
module tb_camera_sccb_slow;
 reg clk=0,rst=1,start=0,read_en=0,present=1,hold_scl=0;
 always #10 clk=~clk;
 reg [7:0] addr=0,data=0;
 tri1 #(8000,0) scl,sda;
 wire busy,done;
 wire [1:0] error;
 wire [7:0] read_data;
 wire [15:0] live,failure;
 camera_sccb #(.CLOCK_HZ(50000000),.BUS_HZ(10000)) dut(
  .clk(clk),.rst(rst),.start(start),.read_en(read_en),.reg_addr(addr),.write_data(data),
  .busy(busy),.done(done),.error(error),.read_data(read_data),.scl(scl),.sda(sda),
  .debug_live(live),.debug_failure(failure));
 ov2640_model sensor(.present(present),.bad_id(1'b0),.hold_scl(hold_scl),.scl(scl),.sda(sda));
 task transaction;
  input rd;
  input [7:0] reg_addr,value,expected;
  input [1:0] expected_error;
  begin
   @(negedge clk); read_en=rd; addr=reg_addr; data=value; start=1;
   @(negedge clk); start=0;
   wait(done); #1;
   if(error!==expected_error) $fatal(1,"Slow SCCB error=%d expected=%d state=%h",error,expected_error,failure);
   if(rd && expected_error==0 && read_data!==expected) $fatal(1,"Slow read %h got %h expected %h",reg_addr,read_data,expected);
   repeat(2000) @(negedge clk);
  end
 endtask
 initial begin
  repeat(2000) @(negedge clk); rst=0;
  transaction(0,8'hff,8'h01,0,0);
  transaction(1,8'h0a,0,8'h26,0);
  transaction(1,8'h0b,0,8'h42,0);
  transaction(0,8'h55,8'ha5,0,0);
  transaction(1,8'h55,0,8'ha5,0);
  present=0;
  transaction(0,8'hff,8'h01,0,1);
  present=1; hold_scl=1;
  transaction(0,8'hff,8'h01,0,2);
  if(failure[4:0]!==1 || failure[6]!==0) $fatal(1,"Slow bus timeout diagnostic incorrect");
  $display("ALL CAMERA SLOW SCCB TESTS PASS: 10 kHz, delayed rise, ID, readback, NACK, timeout");
  $finish;
 end
 initial begin #100000000; $fatal(1,"Slow SCCB simulation watchdog"); end
endmodule
