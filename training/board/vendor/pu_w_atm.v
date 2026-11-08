// -----------------------------------------------------------------
//                 Copyright (c) 2024 pangomicro 
//                       ALL RIGHTS RESERVED
// -----------------------------------------------------------------
// Filename      : pu_w_atm.v
// Author        :  
// Created On    : 2024-09-20 15:24
// Last Modified : 
// -----------------------------------------------------------------
//-----------------------------------------------------------------------------
// Description: Write Channel for ATM
// Verilog-standard:  Verilog 2001
//--------------------------------------------------------------------------
`timescale 1ps/1ps

module pu_w_atm #
  (
   parameter         C_FAMILY                         = "rtl",
                       // FPGA Family. Current version: KOSMO2
   parameter integer C_AXI_ID_WIDTH                   = 4,
                       // Width of all ID signals on SI and MI side of checker.
                       // Range: >= 1.
   parameter integer C_AXI_DATA_WIDTH                 = 64,
                       // Width of all DATA signals on SI and MI side of checker.
                       // Range: 64.
   parameter integer C_AXI_WUSER_WIDTH                = 1
                       // Width of AWUSER signals. 
                       // Range: >= 1.
   )
  (
   // Global Signals
   input  wire                                  ARESET,
   input  wire                                  ACLK,

   // Command Interface (In)
   input  wire                                  cmd_w_valid,
   input  wire                                  cmd_w_check,
   input  wire [C_AXI_ID_WIDTH-1:0]             cmd_w_id,
   output wire                                  cmd_w_ready,
   
   // Command Interface (Out)
   output wire                                  cmd_b_push,
   output wire                                  cmd_b_error,
   output reg  [C_AXI_ID_WIDTH-1:0]             cmd_b_id,
   input  wire                                  cmd_b_full,
   
   // Slave Interface Write Port
   input  wire [C_AXI_ID_WIDTH-1:0]             S_AXI_WID,
   input  wire [C_AXI_DATA_WIDTH-1:0]           S_AXI_WDATA,
   input  wire [C_AXI_DATA_WIDTH/8-1:0]         S_AXI_WSTRB,
   input  wire                                  S_AXI_WLAST,
   input  wire [C_AXI_WUSER_WIDTH-1:0]          S_AXI_WUSER,
   input  wire                                  S_AXI_WVALID,
   output wire                                  S_AXI_WREADY,

   // Master Interface Write Address Port
   output wire [C_AXI_ID_WIDTH-1:0]             M_AXI_WID,
   output wire [C_AXI_DATA_WIDTH-1:0]           M_AXI_WDATA,
   output wire [C_AXI_DATA_WIDTH/8-1:0]         M_AXI_WSTRB,
   output wire                                  M_AXI_WLAST,
   output wire [C_AXI_WUSER_WIDTH-1:0]          M_AXI_WUSER,
   output wire                                  M_AXI_WVALID,
   input  wire                                  M_AXI_WREADY
   );
  
  //---------------------------------------------------------------------------
  // Internal signals
  //---------------------------------------------------------------------------
  
  // Detecttion.
  wire                                any_strb_deasserted;
  wire                                incoming_strb_issue;
  reg                                 first_word;
  reg                                 strb_issue;
  
  // Data flow.
  wire                                data_pop;
  wire                                cmd_b_push_blocked;
  reg                                 cmd_b_push_i;
  
  
  //---------------------------------------------------------------------------
  // Detect error:
  //
  // Detect and accumulate error when a transaction shall be scanned for
  // potential issues.
  // Accumulation of error is restarted for each ne transaction. 
  //---------------------------------------------------------------------------
  
  // Check stobe information
  assign any_strb_deasserted  = ( S_AXI_WSTRB != {C_AXI_DATA_WIDTH/8{1'b1}} );
  assign incoming_strb_issue  = cmd_w_valid & S_AXI_WVALID & cmd_w_check & any_strb_deasserted;
  
  // Keep track of first word in a transaction.
  always @ (posedge ACLK) begin
    if (ARESET) begin
      first_word  <= 1'b1;
    end else if ( data_pop ) begin
      first_word  <= S_AXI_WLAST;
    end
  end
  
  // Keep track of error status.
  always @ (posedge ACLK) begin
    if (ARESET) begin
      strb_issue  <= 1'b0;
      cmd_b_id    <= {C_AXI_ID_WIDTH{1'b0}};
    end else if ( data_pop ) begin
      if ( first_word ) begin
        strb_issue  <= incoming_strb_issue;
      end else begin
        strb_issue  <= incoming_strb_issue | strb_issue;
      end
      cmd_b_id    <= cmd_w_id;
    end
  end
  
  assign cmd_b_error  = strb_issue;
  
  
  //---------------------------------------------------------------------------
  // Control command queue to B:
  //
  // Push command to B queue when all data for the transaction has flowed  
  // through.
  // Delay pipelined command until there is room in the Queue.
  // 
  //---------------------------------------------------------------------------
  
  // Detect when data is popped.
  assign data_pop   = S_AXI_WVALID & M_AXI_WREADY & cmd_w_valid & ~cmd_b_full & ~cmd_b_push_blocked; 
  
  // Push command when last word in transfered (pipelined).
  always @ (posedge ACLK) begin
    if (ARESET) begin
      cmd_b_push_i  <= 1'b0;
    end else begin
      cmd_b_push_i  <= ( S_AXI_WLAST & data_pop ) | cmd_b_push_blocked;
    end
  end
  
  // Detect if pipelined push is blocked.
  assign cmd_b_push_blocked = cmd_b_push_i & cmd_b_full;
  
  // Assign output.
  assign cmd_b_push = cmd_b_push_i & ~cmd_b_full;
  
  
  //---------------------------------------------------------------------------
  // Transaction Throttling:
  //
  // Stall commands if FIFO is full or there is no valid command information 
  // from AW. 
  // 
  //---------------------------------------------------------------------------
  
  // Propagate masked valid.
  assign M_AXI_WVALID   = S_AXI_WVALID & cmd_w_valid & ~cmd_b_full & ~cmd_b_push_blocked;
  
  // Return ready with push back.
  assign S_AXI_WREADY   = M_AXI_WREADY & cmd_w_valid & ~cmd_b_full & ~cmd_b_push_blocked;
  
  // End of burst.
  assign cmd_w_ready    = S_AXI_WVALID & M_AXI_WREADY & cmd_w_valid & ~cmd_b_full & ~cmd_b_push_blocked & S_AXI_WLAST;
  
  // 1:1 mapping.
  assign M_AXI_WID      = S_AXI_WID;
  assign M_AXI_WDATA    = S_AXI_WDATA;
  assign M_AXI_WSTRB    = S_AXI_WSTRB;
  assign M_AXI_WLAST    = S_AXI_WLAST;
  assign M_AXI_WUSER    = S_AXI_WUSER;
  
  
endmodule
