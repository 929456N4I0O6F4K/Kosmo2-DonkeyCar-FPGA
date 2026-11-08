// -----------------------------------------------------------------
//                 Copyright (c) 2024 pangomicro 
//                       ALL RIGHTS RESERVED
// -----------------------------------------------------------------
// Filename      : pu_b_atm.v
// Author        :  
// Created On    : 2024-09-19 15:24
// Last Modified : 
// -----------------------------------------------------------------
//-----------------------------------------------------------------------------
// Description: Write Response Channel for ATM
// Verilog-standard:  Verilog 2001
//--------------------------------------------------------------------------
`timescale 1ps/1ps

module pu_b_atm #
  (
   parameter         C_FAMILY                         = "rtl", 
                       // FPGA Family. Current version: KOSMO2
   parameter integer C_AXI_ID_WIDTH                   = 4, 
                       // Width of all ID signals on SI and MI side of checker.
                       // Range: >= 1.
   parameter integer C_AXI_BUSER_WIDTH                = 1,
                       // Width of AWUSER signals. 
                       // Range: >= 1.
   parameter integer C_FIFO_DEPTH_LOG                 = 4
   )
  (
   // Global Signals
   input  wire                                  ARESET,
   input  wire                                  ACLK,

   // Command Interface
   input  wire                                  cmd_b_push,
   input  wire                                  cmd_b_error,
   input  wire [C_AXI_ID_WIDTH-1:0]             cmd_b_id,
   output wire                                  cmd_b_ready,
   output wire [C_FIFO_DEPTH_LOG-1:0]           cmd_b_addr,
   output reg                                   cmd_b_full,
   
   // Slave Interface Write Response Ports
   output wire [C_AXI_ID_WIDTH-1:0]             S_AXI_BID,
   output reg  [2-1:0]                          S_AXI_BRESP,
   output wire [C_AXI_BUSER_WIDTH-1:0]          S_AXI_BUSER,
   output wire                                  S_AXI_BVALID,
   input  wire                                  S_AXI_BREADY,

   // Master Interface Write Response Ports
   input  wire [C_AXI_ID_WIDTH-1:0]             M_AXI_BID,
   input  wire [2-1:0]                          M_AXI_BRESP,
   input  wire [C_AXI_BUSER_WIDTH-1:0]          M_AXI_BUSER,
   input  wire                                  M_AXI_BVALID,
   output wire                                  M_AXI_BREADY,
   
   // Trigger detection
   output reg                                   ERROR_INDICATION,
   output reg  [C_AXI_ID_WIDTH-1:0]             ERROR_TRANSACTION_ID
   );
  
  
  //---------------------------------------------------------------------------
  // Local params
  //---------------------------------------------------------------------------
  
  // Constants for packing levels.
  localparam [2-1:0] C_RESP_OKAY         = 2'b00;
  localparam [2-1:0] C_RESP_EXOKAY       = 2'b01;
  localparam [2-1:0] C_RESP_SLVERROR     = 2'b10;
  localparam [2-1:0] C_RESP_DECERR       = 2'b11;
  
  // Command FIFO settings
  localparam C_FIFO_WIDTH                = C_AXI_ID_WIDTH + 1;
  localparam C_FIFO_DEPTH                = 2 ** C_FIFO_DEPTH_LOG;
    
  
  //---------------------------------------------------------------------------
  // Variables for generating parameter controlled instances.
  //---------------------------------------------------------------------------
  
  integer index;
  
  //---------------------------------------------------------------------------
  // Internal signals
  //---------------------------------------------------------------------------
  
  // Command Queue.
  reg  [C_FIFO_DEPTH_LOG-1:0]         addr_ptr;
  reg  [C_FIFO_WIDTH-1:0]             data_srl[C_FIFO_DEPTH-1:0];
  reg                                 cmd_b_valid;
  wire                                cmd_b_ready_i;
  wire                                inject_error;
  wire [C_AXI_ID_WIDTH-1:0]           current_id;
  
  // Search command.
  wire                                found_match;
  wire                                use_match;
  wire                                matching_id;
  
  // Manage valid command.
  wire                                write_valid_cmd;
  reg  [C_FIFO_DEPTH-2:0]             valid_cmd;
  reg  [C_FIFO_DEPTH-2:0]             updated_valid_cmd;
  reg  [C_FIFO_DEPTH-2:0]             next_valid_cmd;
  reg  [C_FIFO_DEPTH_LOG-1:0]         search_addr_ptr;
  reg  [C_FIFO_DEPTH_LOG-1:0]         collapsed_addr_ptr;
  
  // Pipelined data
  reg  [C_AXI_ID_WIDTH-1:0]           M_AXI_BID_I;
  reg  [2-1:0]                        M_AXI_BRESP_I;
  reg  [C_AXI_BUSER_WIDTH-1:0]        M_AXI_BUSER_I;
  reg                                 M_AXI_BVALID_I;
  wire                                M_AXI_BREADY_I;
  
  
  //---------------------------------------------------------------------------
  // Command Queue:
  // Keep track of depth of Queue to generate full flag.
  // Also generate valid to mark pressence of commands in Queue.
  // Maintain Queue and extract data from currently searched entry.
  //---------------------------------------------------------------------------
  
  // SRL FIFO Pointer.
  always @ (posedge ACLK) begin
    if (ARESET) begin
      addr_ptr <= {C_FIFO_DEPTH_LOG{1'b1}};
    end else begin
      if ( cmd_b_push & ~cmd_b_ready_i ) begin
        // Pushing data increase length/addr.
        addr_ptr <= addr_ptr + 1;
      end else if ( cmd_b_ready_i ) begin
        // Collapse addr when data is popped.
        addr_ptr <= collapsed_addr_ptr;
      end
    end
  end
  
  // FIFO Flags.
  always @ (posedge ACLK) begin
    if (ARESET) begin
      cmd_b_full  <= 1'b0;
      cmd_b_valid <= 1'b0;
    end else begin
      if ( cmd_b_push & ~cmd_b_ready_i ) begin
        cmd_b_full  <= ( addr_ptr == C_FIFO_DEPTH-3 );
        cmd_b_valid <= 1'b1;
      end else if ( ~cmd_b_push & cmd_b_ready_i ) begin
        cmd_b_full  <= 1'b0;
        cmd_b_valid <= ( collapsed_addr_ptr != C_FIFO_DEPTH-1 );
      end
    end
  end
  
  // Infere SRL for storage.
  always @ (posedge ACLK) begin
    if ( cmd_b_push ) begin
      for (index = 0; index < C_FIFO_DEPTH-1 ; index = index + 1) begin
        data_srl[index+1] <= data_srl[index];
      end
      data_srl[0]   <= {cmd_b_error, cmd_b_id};
    end
  end
  
  // Get current transaction info.
  assign {inject_error, current_id} = data_srl[search_addr_ptr];
  
  // Assign outputs.
  assign cmd_b_addr = collapsed_addr_ptr;
  
  //---------------------------------------------------------------------------
  // Search Command Queue:
  //
  // Search for matching valid command in queue.
  // 
  // A command is found when an valid entry with correct ID is found. The queue
  // is search from the oldest entry, i.e. from a high value.
  // When new commands are pushed the search address has to be updated to always 
  // start the search from the oldest available.
  // 
  //---------------------------------------------------------------------------
  
  // Handle search addr.
  always @ (posedge ACLK) begin
    if (ARESET) begin
      search_addr_ptr <= {C_FIFO_DEPTH_LOG{1'b1}};
    end else begin
      if ( cmd_b_ready_i ) begin
        // Collapse addr when data is popped.
        search_addr_ptr <= collapsed_addr_ptr;
        
      end else if ( M_AXI_BVALID_I & cmd_b_valid & ~found_match & ~cmd_b_push ) begin
        // Skip non valid command.
        search_addr_ptr <= search_addr_ptr - 1;
        
      end else if ( cmd_b_push ) begin
        search_addr_ptr <= search_addr_ptr + 1;
        
      end
    end
  end
  
  // Check if searched command is valid and match ID (for existing response on MI side).
  assign matching_id  = ( M_AXI_BID_I == current_id );
  assign found_match  = valid_cmd[search_addr_ptr] & matching_id & M_AXI_BVALID_I;
  assign use_match    = found_match & S_AXI_BREADY;
  
  
  //---------------------------------------------------------------------------
  // Track Used Commands:
  // Actions that affect Valid Command:
  // * When a new command is pushed
  //   => Shift valid vector one step
  // * When a command is used
  //   => Clear corresponding valid bit
  //---------------------------------------------------------------------------
  
  // Valid command status is updated when a command is used or a new one is pushed.
  assign write_valid_cmd  = cmd_b_push | cmd_b_ready_i;
  
  // Update the used command valid bit.
  always @ *
  begin
    updated_valid_cmd                   = valid_cmd;
    updated_valid_cmd[search_addr_ptr]  = ~use_match;
  end
  
  // Shift valid vector when command is pushed.
  always @ *
  begin
    if ( cmd_b_push ) begin
      next_valid_cmd = {updated_valid_cmd[C_FIFO_DEPTH-3:0], 1'b1};
    end else begin
      next_valid_cmd = updated_valid_cmd;
    end
  end
  
  // Valid signals for next cycle.
  always @ (posedge ACLK) begin
    if (ARESET) begin
      valid_cmd <= {C_FIFO_WIDTH{1'b0}};
    end else if ( write_valid_cmd ) begin
      valid_cmd <= next_valid_cmd;
    end
  end
  
  // Detect oldest available command in Queue.
  always @ *
  begin
    // Default to empty.
    collapsed_addr_ptr = {C_FIFO_DEPTH_LOG{1'b1}};
    
    for (index = 0; index < C_FIFO_DEPTH-2 ; index = index + 1) begin
      if ( next_valid_cmd[index] ) begin
        collapsed_addr_ptr = index;
      end
    end
  end
  
  //---------------------------------------------------------------------------
  // Pipe incoming data:
  // The B channel is piped to improve timing and avoid impact in search
  // mechanism due to late arriving signals.
  //---------------------------------------------------------------------------
  
  // Clock data.
  always @ (posedge ACLK) begin
    if (ARESET) begin
      M_AXI_BID_I     <= {C_AXI_ID_WIDTH{1'b0}};
      M_AXI_BRESP_I   <= 2'b00;
      M_AXI_BUSER_I   <= {C_AXI_BUSER_WIDTH{1'b0}};
      M_AXI_BVALID_I  <= 1'b0;
    end else begin
      if ( M_AXI_BREADY_I | ~M_AXI_BVALID_I ) begin
        M_AXI_BVALID_I  <= 1'b0;
      end
      if (M_AXI_BVALID & ( M_AXI_BREADY_I | ~M_AXI_BVALID_I) ) begin
        M_AXI_BID_I     <= M_AXI_BID;
        M_AXI_BRESP_I   <= M_AXI_BRESP;
        M_AXI_BUSER_I   <= M_AXI_BUSER;
        M_AXI_BVALID_I  <= 1'b1;
      end
    end
  end
  
  // Generate ready to get new transaction.
  assign M_AXI_BREADY = M_AXI_BREADY_I | ~M_AXI_BVALID_I;
  
  //---------------------------------------------------------------------------
  // Inject Error:
  // BRESP is modified according to command information.
  //---------------------------------------------------------------------------
  
  // Inject error in response.
  always @ *
  begin
    if ( inject_error ) begin
      S_AXI_BRESP = C_RESP_SLVERROR;
    end else begin
      S_AXI_BRESP = M_AXI_BRESP_I;
    end
  end
  
  // Handle interrupt generation.
  always @ (posedge ACLK) begin
    if (ARESET) begin
      ERROR_INDICATION        <= 1'b0;
      ERROR_TRANSACTION_ID <= {C_AXI_ID_WIDTH{1'b0}};
    end else begin
      if ( inject_error & cmd_b_ready_i ) begin
        ERROR_INDICATION        <= 1'b1;
        ERROR_TRANSACTION_ID <= M_AXI_BID_I;
      end else begin
        ERROR_INDICATION        <= 1'b0;
      end
    end
  end
  
  //---------------------------------------------------------------------------
  // Transaction Throttling:
  //
  // Response is passed forward when a matching entry has been found in queue.
  // Both ready and valid are set when the command is completed.
  //---------------------------------------------------------------------------
  
  // Propagate masked valid.
  assign S_AXI_BVALID   = M_AXI_BVALID_I & cmd_b_valid & found_match;
  
  // Return ready with push back.
  assign M_AXI_BREADY_I = cmd_b_valid & use_match;
  
  // Command has been handled.
  assign cmd_b_ready_i  = M_AXI_BVALID_I & cmd_b_valid & use_match;
  assign cmd_b_ready    = cmd_b_ready_i;
  
  //---------------------------------------------------------------------------
  // Write Response Propagation:
  //
  // All information is simply forwarded on from MI- to SI-Side untouched.
  //---------------------------------------------------------------------------
  
  // 1:1 mapping.
  assign S_AXI_BID    = M_AXI_BID_I;
  assign S_AXI_BUSER  = M_AXI_BUSER_I;
  
  
endmodule
