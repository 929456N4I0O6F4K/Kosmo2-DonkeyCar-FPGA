// -----------------------------------------------------------------
//                 Copyright (c) 2024 pangomicro 
//                       ALL RIGHTS RESERVED
// -----------------------------------------------------------------
// Filename      : pu_atm.v
// Author        :  
// Created On    : 2024-09-22 15:24
// Last Modified : 
// -----------------------------------------------------------------
//-----------------------------------------------------------------------------
//
// Description: ACP Transaction monitor
// 
// monitor the input transactions and if there are broken transactions, give a indication that 
// the transactions is wrong 
//
// Verilog-standard:  Verilog 2001
//--------------------------------------------------------------------------
//
// Structure:
//   pu_atm
//     pu_aw_atm
//     pu_w_atm
//     pu_b_atm
//
//--------------------------------------------------------------------------
`timescale 1ps/1ps
`default_nettype none

module pu_atm #
  (
   parameter         C_FAMILY                         = "rtl",
                       // FPGA Family. Current version: KOSMO2.
   parameter integer C_AXI_ID_WIDTH                   = 4,
                       // Width of all ID signals on SI and MI side of checker.
                       // Range: >= 1.
   parameter integer C_AXI_ADDR_WIDTH                 = 32,
                       // Width of all ADDR signals on SI and MI side of checker.
                       // Range: 32.
   parameter integer C_AXI_DATA_WIDTH                 = 64,
                       // Width of all DATA signals on SI and MI side of checker.
                       // Range: 64.
   parameter integer C_AXI_AWUSER_WIDTH               = 1,
                       // Width of AWUSER signals. 
                       // Range: >= 1.
   parameter integer C_AXI_ARUSER_WIDTH               = 1,
                       // Width of ARUSER signals. 
                       // Range: >= 1.
   parameter integer C_AXI_WUSER_WIDTH                = 1,
                       // Width of WUSER signals. 
                       // Range: >= 1.
   parameter integer C_AXI_RUSER_WIDTH                = 1,
                       // Width of RUSER signals. 
                       // Range: >= 1.
   parameter integer C_AXI_BUSER_WIDTH                = 1
                       // Width of BUSER signals. 
                       // Range: >= 1.
   )
  (
   // Global Signals
   input  wire                                  ACLK,
   input  wire                                  ARESETN,

   // Slave Interface Write Address Ports
   input  wire [C_AXI_ID_WIDTH-1:0]             S_AXI_AWID,
   input  wire [C_AXI_ADDR_WIDTH-1:0]           S_AXI_AWADDR,
   input  wire [4-1:0]                          S_AXI_AWLEN,
   input  wire [3-1:0]                          S_AXI_AWSIZE,
   input  wire [2-1:0]                          S_AXI_AWBURST,
   input  wire [2-1:0]                          S_AXI_AWLOCK,
   input  wire [4-1:0]                          S_AXI_AWCACHE,
   input  wire [3-1:0]                          S_AXI_AWPROT,
   input  wire [C_AXI_AWUSER_WIDTH-1:0]         S_AXI_AWUSER,
   input  wire                                  S_AXI_AWVALID,
   output wire                                  S_AXI_AWREADY,
   // Slave Interface Write Data Ports
   input  wire [C_AXI_ID_WIDTH-1:0]             S_AXI_WID,
   input  wire [C_AXI_DATA_WIDTH-1:0]           S_AXI_WDATA,
   input  wire [C_AXI_DATA_WIDTH/8-1:0]         S_AXI_WSTRB,
   input  wire                                  S_AXI_WLAST,
   input  wire [C_AXI_WUSER_WIDTH-1:0]          S_AXI_WUSER,
   input  wire                                  S_AXI_WVALID,
   output wire                                  S_AXI_WREADY,
   // Slave Interface Write Response Ports
   output wire [C_AXI_ID_WIDTH-1:0]             S_AXI_BID,
   output wire [2-1:0]                          S_AXI_BRESP,
   output wire [C_AXI_BUSER_WIDTH-1:0]          S_AXI_BUSER,
   output wire                                  S_AXI_BVALID,
   input  wire                                  S_AXI_BREADY,
   // Slave Interface Read Address Ports
   input  wire [C_AXI_ID_WIDTH-1:0]             S_AXI_ARID,
   input  wire [C_AXI_ADDR_WIDTH-1:0]           S_AXI_ARADDR,
   input  wire [4-1:0]                          S_AXI_ARLEN,
   input  wire [3-1:0]                          S_AXI_ARSIZE,
   input  wire [2-1:0]                          S_AXI_ARBURST,
   input  wire [2-1:0]                          S_AXI_ARLOCK,
   input  wire [4-1:0]                          S_AXI_ARCACHE,
   input  wire [3-1:0]                          S_AXI_ARPROT,
   input  wire [C_AXI_ARUSER_WIDTH-1:0]         S_AXI_ARUSER,
   input  wire                                  S_AXI_ARVALID,
   output wire                                  S_AXI_ARREADY,
   // Slave Interface Read Data Ports
   output wire [C_AXI_ID_WIDTH-1:0]             S_AXI_RID,
   output wire [C_AXI_DATA_WIDTH-1:0]           S_AXI_RDATA,
   output wire [2-1:0]                          S_AXI_RRESP,
   output wire                                  S_AXI_RLAST,
   output wire [C_AXI_RUSER_WIDTH-1:0]          S_AXI_RUSER,
   output wire                                  S_AXI_RVALID,
   input  wire                                  S_AXI_RREADY,

   // Master Interface Write Address Port
   output wire [C_AXI_ID_WIDTH-1:0]             M_AXI_AWID,
   output wire [C_AXI_ADDR_WIDTH-1:0]           M_AXI_AWADDR,
   output wire [4-1:0]                          M_AXI_AWLEN,
   output wire [3-1:0]                          M_AXI_AWSIZE,
   output wire [2-1:0]                          M_AXI_AWBURST,
   output wire [2-1:0]                          M_AXI_AWLOCK,
   output wire [4-1:0]                          M_AXI_AWCACHE,
   output wire [3-1:0]                          M_AXI_AWPROT,
   output wire [C_AXI_AWUSER_WIDTH-1:0]         M_AXI_AWUSER,
   output wire                                  M_AXI_AWVALID,
   input  wire                                  M_AXI_AWREADY,
   // Master Interface Write Data Ports
   output wire [C_AXI_ID_WIDTH-1:0]             M_AXI_WID,
   output wire [C_AXI_DATA_WIDTH-1:0]           M_AXI_WDATA,
   output wire [C_AXI_DATA_WIDTH/8-1:0]         M_AXI_WSTRB,
   output wire                                  M_AXI_WLAST,
   output wire [C_AXI_WUSER_WIDTH-1:0]          M_AXI_WUSER,
   output wire                                  M_AXI_WVALID,
   input  wire                                  M_AXI_WREADY,
   // Master Interface Write Response Ports
   input  wire [C_AXI_ID_WIDTH-1:0]             M_AXI_BID,
   input  wire [2-1:0]                          M_AXI_BRESP,
   input  wire [C_AXI_BUSER_WIDTH-1:0]          M_AXI_BUSER,
   input  wire                                  M_AXI_BVALID,
   output wire                                  M_AXI_BREADY,
   // Master Interface Read Address Port
   output wire [C_AXI_ID_WIDTH-1:0]             M_AXI_ARID,
   output wire [C_AXI_ADDR_WIDTH-1:0]           M_AXI_ARADDR,
   output wire [4-1:0]                          M_AXI_ARLEN,
   output wire [3-1:0]                          M_AXI_ARSIZE,
   output wire [2-1:0]                          M_AXI_ARBURST,
   output wire [2-1:0]                          M_AXI_ARLOCK,
   output wire [4-1:0]                          M_AXI_ARCACHE,
   output wire [3-1:0]                          M_AXI_ARPROT,
   output wire [C_AXI_ARUSER_WIDTH-1:0]         M_AXI_ARUSER,
   output wire                                  M_AXI_ARVALID,
   input  wire                                  M_AXI_ARREADY,
   // Master Interface Read Data Ports
   input  wire [C_AXI_ID_WIDTH-1:0]             M_AXI_RID,
   input  wire [C_AXI_DATA_WIDTH-1:0]           M_AXI_RDATA,
   input  wire [2-1:0]                          M_AXI_RRESP,
   input  wire                                  M_AXI_RLAST,
   input  wire [C_AXI_RUSER_WIDTH-1:0]          M_AXI_RUSER,
   input  wire                                  M_AXI_RVALID,
   output wire                                  M_AXI_RREADY,
   
   output wire                                  ERROR_INDICATION,
   output wire [C_AXI_ID_WIDTH-1:0]             ERROR_TRANSACTION_ID
   );

  //---------------------------------------------------------------------------
  // Local params
  //---------------------------------------------------------------------------
  
  localparam C_FIFO_DEPTH_LOG            = 4;
  
  
  //---------------------------------------------------------------------------
  // Internal signals
  //---------------------------------------------------------------------------
  
  // Internal reset.
  reg                                   ARESET;
  
  // AW->W command queue signals.
  wire                                  cmd_w_valid;
  wire                                  cmd_w_check;
  wire [C_AXI_ID_WIDTH-1:0]             cmd_w_id;
  wire                                  cmd_w_ready;
  
  // W->B command queue signals.
  wire                                  cmd_b_push;
  wire                                  cmd_b_error;
  wire [C_AXI_ID_WIDTH-1:0]             cmd_b_id;
  wire                                  cmd_b_full;
  wire [C_FIFO_DEPTH_LOG-1:0]           cmd_b_addr;
  wire                                  cmd_b_ready;
  

  //---------------------------------------------------------------------------
  // Handle Internal Reset
  //---------------------------------------------------------------------------
  always @ (posedge ACLK) begin
    ARESET <= !ARESETN;
  end
  
  
  //---------------------------------------------------------------------------
  // Handle Write Channels (AW/W/B)
  //---------------------------------------------------------------------------
  
  // Write Address Channel.
  pu_aw_atm #
  (
   .C_FAMILY                    (C_FAMILY),
   .C_AXI_ID_WIDTH              (C_AXI_ID_WIDTH),
   .C_AXI_ADDR_WIDTH            (C_AXI_ADDR_WIDTH),
   .C_AXI_AWUSER_WIDTH          (C_AXI_AWUSER_WIDTH),
   .C_FIFO_DEPTH_LOG            (C_FIFO_DEPTH_LOG)
    ) write_addr_inst
   (
    // Global Signals
    .ARESET                     (ARESET),
    .ACLK                       (ACLK),

    // Command Interface (Out)
    .cmd_w_valid                (cmd_w_valid),
    .cmd_w_check                (cmd_w_check),
    .cmd_w_id                   (cmd_w_id),
    .cmd_w_ready                (cmd_w_ready),
    .cmd_b_addr                 (cmd_b_addr),
    .cmd_b_ready                (cmd_b_ready),
   
    // Slave Interface Write Address Ports
    .S_AXI_AWID                 (S_AXI_AWID),
    .S_AXI_AWADDR               (S_AXI_AWADDR),
    .S_AXI_AWLEN                (S_AXI_AWLEN),
    .S_AXI_AWSIZE               (S_AXI_AWSIZE),
    .S_AXI_AWBURST              (S_AXI_AWBURST),
    .S_AXI_AWLOCK               (S_AXI_AWLOCK),
    .S_AXI_AWCACHE              (S_AXI_AWCACHE),
    .S_AXI_AWPROT               (S_AXI_AWPROT),
    .S_AXI_AWUSER               (S_AXI_AWUSER),
    .S_AXI_AWVALID              (S_AXI_AWVALID),
    .S_AXI_AWREADY              (S_AXI_AWREADY),
    
    // Master Interface Write Address Port
    .M_AXI_AWID                 (M_AXI_AWID),
    .M_AXI_AWADDR               (M_AXI_AWADDR),
    .M_AXI_AWLEN                (M_AXI_AWLEN),
    .M_AXI_AWSIZE               (M_AXI_AWSIZE),
    .M_AXI_AWBURST              (M_AXI_AWBURST),
    .M_AXI_AWLOCK               (M_AXI_AWLOCK),
    .M_AXI_AWCACHE              (M_AXI_AWCACHE),
    .M_AXI_AWPROT               (M_AXI_AWPROT),
    .M_AXI_AWUSER               (M_AXI_AWUSER),
    .M_AXI_AWVALID              (M_AXI_AWVALID),
    .M_AXI_AWREADY              (M_AXI_AWREADY)
   );
   
  // Write Data channel.
  pu_w_atm #
  (
   .C_FAMILY                    (C_FAMILY),
   .C_AXI_ID_WIDTH              (C_AXI_ID_WIDTH),
   .C_AXI_DATA_WIDTH            (C_AXI_DATA_WIDTH),
   .C_AXI_WUSER_WIDTH           (C_AXI_WUSER_WIDTH)
    ) write_data_inst
   (
    // Global Signals
    .ARESET                     (ARESET),
    .ACLK                       (ACLK),

    // Command Interface (In)
    .cmd_w_valid                (cmd_w_valid),
    .cmd_w_check                (cmd_w_check),
    .cmd_w_id                   (cmd_w_id),
    .cmd_w_ready                (cmd_w_ready),
    
    // Command Interface (Out)
    .cmd_b_push                 (cmd_b_push),
    .cmd_b_error                (cmd_b_error),
    .cmd_b_id                   (cmd_b_id),
    .cmd_b_full                 (cmd_b_full),
    
    // Slave Interface Write Data Ports
    .S_AXI_WID                  (S_AXI_WID),
    .S_AXI_WDATA                (S_AXI_WDATA),
    .S_AXI_WSTRB                (S_AXI_WSTRB),
    .S_AXI_WLAST                (S_AXI_WLAST),
    .S_AXI_WUSER                (S_AXI_WUSER),
    .S_AXI_WVALID               (S_AXI_WVALID),
    .S_AXI_WREADY               (S_AXI_WREADY),
    
    // Master Interface Write Data Ports
    .M_AXI_WID                  (M_AXI_WID),
    .M_AXI_WDATA                (M_AXI_WDATA),
    .M_AXI_WSTRB                (M_AXI_WSTRB),
    .M_AXI_WLAST                (M_AXI_WLAST),
    .M_AXI_WUSER                (M_AXI_WUSER),
    .M_AXI_WVALID               (M_AXI_WVALID),
    .M_AXI_WREADY               (M_AXI_WREADY)
   );
   
  // Write Response channel.
 pu_b_atm #
  (
   .C_FAMILY                    (C_FAMILY),
   .C_AXI_ID_WIDTH              (C_AXI_ID_WIDTH),
   .C_AXI_BUSER_WIDTH           (C_AXI_BUSER_WIDTH),
   .C_FIFO_DEPTH_LOG            (C_FIFO_DEPTH_LOG)
    ) write_response_inst
   (
    // Global Signals
    .ARESET                     (ARESET),
    .ACLK                       (ACLK),

    // Command Interface (In)
    .cmd_b_push                 (cmd_b_push),
    .cmd_b_error                (cmd_b_error),
    .cmd_b_id                   (cmd_b_id),
    .cmd_b_full                 (cmd_b_full),
    .cmd_b_addr                 (cmd_b_addr),
    .cmd_b_ready                (cmd_b_ready),
    
    // Slave Interface Write Response Ports
    .S_AXI_BID                  (S_AXI_BID),
    .S_AXI_BRESP                (S_AXI_BRESP),
    .S_AXI_BUSER                (S_AXI_BUSER),
    .S_AXI_BVALID               (S_AXI_BVALID),
    .S_AXI_BREADY               (S_AXI_BREADY),
    
    // Master Interface Write Response Ports
    .M_AXI_BID                  (M_AXI_BID),
    .M_AXI_BRESP                (M_AXI_BRESP),
    .M_AXI_BUSER                (M_AXI_BUSER),
    .M_AXI_BVALID               (M_AXI_BVALID),
    .M_AXI_BREADY               (M_AXI_BREADY),
    
    // Trigger detection
    .ERROR_INDICATION           (ERROR_INDICATION),
    .ERROR_TRANSACTION_ID       (ERROR_TRANSACTION_ID)
   );
  
  
  
  //---------------------------------------------------------------------------
  // Handle Read Channels (AR/R)
  //---------------------------------------------------------------------------
  // Read Address Port
  assign M_AXI_ARID     = S_AXI_ARID;
  assign M_AXI_ARADDR   = S_AXI_ARADDR;
  assign M_AXI_ARLEN    = S_AXI_ARLEN;
  assign M_AXI_ARSIZE   = S_AXI_ARSIZE;
  assign M_AXI_ARBURST  = S_AXI_ARBURST;
  assign M_AXI_ARLOCK   = S_AXI_ARLOCK;
  assign M_AXI_ARCACHE  = S_AXI_ARCACHE;
  assign M_AXI_ARPROT   = S_AXI_ARPROT;
  assign M_AXI_ARUSER   = S_AXI_ARUSER;
  assign M_AXI_ARVALID  = S_AXI_ARVALID;
  assign S_AXI_ARREADY  = M_AXI_ARREADY;
   
  // Read Data Port
  assign S_AXI_RID      = M_AXI_RID;
  assign S_AXI_RDATA    = M_AXI_RDATA;
  assign S_AXI_RRESP    = M_AXI_RRESP;
  assign S_AXI_RLAST    = M_AXI_RLAST;
  assign S_AXI_RUSER    = M_AXI_RUSER;
  assign S_AXI_RVALID   = M_AXI_RVALID;
  assign M_AXI_RREADY   = S_AXI_RREADY;
  
  
endmodule
`default_nettype wire
