//////////////////////////////////////////////////////////////////////////////
//
// Copyright (c) 2023 PANGO MICROSYSTEMS, INC
// ALL RIGHTS REVERVED.
//
// THE SOURCE CODE CONTAINED HEREIN IS PROPRIETARY TO PANGO MICROSYSTEMS, INC.
// IT SHALL NOT BE REPRODUCED OR DISCLOSED IN WHOLE OR IN PART OR USED BY
// PARTIES WITHOUT WRITTEN AUTHORIZATION FROM THE OWNER.

module system_process_unit
#(
  parameter integer P_USE_DEFAULT_ACP_USER_VAL = 0,
  parameter integer P_AXI_ACP_ARUSER_VAL = 31,
  parameter integer P_AXI_ACP_AWUSER_VAL = 31,
  parameter integer P_AXI_GP0_THREAD_ID_WIDTH = 12,
  parameter integer P_AXI_GP1_THREAD_ID_WIDTH = 12,
  parameter integer P_AXI_GP0_ENABLE_STATIC_REMAP = 0,
  parameter integer P_AXI_GP1_ENABLE_STATIC_REMAP = 0, 
  parameter integer P_AXI_UPS0_ID_WIDTH = 6,
  parameter integer P_AXI_UPS1_ID_WIDTH = 6,
  parameter integer P_AXI_HP0_ID_WIDTH = 4,
  parameter integer P_AXI_HP1_ID_WIDTH = 4,
  parameter integer P_AXI_HP2_ID_WIDTH = 4,
  parameter integer P_AXI_HP3_ID_WIDTH = 4,
  parameter integer P_AXI_ACP_ID_WIDTH = 5,
  parameter integer P_AXI_HP0_DATA_WIDTH = 128,
  parameter integer P_AXI_HP1_DATA_WIDTH = 128,
  parameter integer P_AXI_HP2_DATA_WIDTH = 64,
  parameter integer P_AXI_HP3_DATA_WIDTH = 64,
  parameter integer P_AXI_ACP_DATA_WIDTH = 128,
  parameter integer P_INCLUDE_ACP_TRANS_CHECK = 0,
  parameter integer P_EMIO_TRACE_WIDTH = 4,
  parameter integer P_EMIO_GPIO_WIDTH = 4,
  parameter integer P_TRACE_PIPELINE_WIDTH = 8,
  parameter integer P_TRACE_BUFFER_FIFO_SIZE = 12,
  parameter integer P_TRACE_DATA_EDGE_DETECTOR = 0,
  parameter integer P_TRACE_BUFFER_CLOCK_DELAY = 0,
  parameter integer P_GENERATE_FIFO = 0,
  parameter integer P_ENABLE_EMIO_TRACE = 0,
  parameter integer P_F2P_INTR_INPUTS_NUM = 20,

  parameter         P_FCLK_CLK0_BUF = "TRUE",
  parameter         P_FCLK_CLK1_BUF = "TRUE",
  parameter         P_FCLK_CLK2_BUF = "TRUE",
  parameter         P_FCLK_CLK3_BUF = "TRUE",
  
  parameter         P_USE_AXI_NONSECURE = 0,
  parameter         P_USE_S_AXI_HP0 = 0,
  parameter         P_USE_S_AXI_HP1 = 0,
  parameter         P_USE_S_AXI_HP2 = 0,
  parameter         P_USE_S_AXI_HP3 = 0,
  parameter         P_USE_M_AXI_GP0 = 0,
  parameter         P_USE_M_AXI_GP1 = 0,
  parameter         P_USE_S_AXI_GP0 = 0,
  parameter         P_USE_S_AXI_GP1 = 0,
  parameter         P_USE_S_AXI_ACP = 0
)(
  input          PU_ACPS_ACLK,
  input          PU_ACPS_AWVALID,
  input  [31:0]  PU_ACPS_AWADDR,
  input  [P_AXI_ACP_ID_WIDTH-1:0]   PU_ACPS_AWID,
  input  [3:0]   PU_ACPS_AWLEN,
  input  [3:0]   PU_ACPS_AWCACHE,
  input  [2:0]   PU_ACPS_AWPROT,
  input          PU_ACPS_WVALID,
  input  [P_AXI_ACP_ID_WIDTH-1:0]   PU_ACPS_WID,
  input  [P_AXI_ACP_DATA_WIDTH-1:0] PU_ACPS_WDATA,
  input  [15:0]  PU_ACPS_WSTRB,
  input          PU_ACPS_WLAST,
  input          PU_ACPS_BREADY,
  input          PU_ACPS_ARVALID,
  input  [P_AXI_ACP_ID_WIDTH-1:0]   PU_ACPS_ARID,
  input  [31:0]  PU_ACPS_ARADDR,
  input  [3:0]   PU_ACPS_ARLEN,
  input  [3:0]   PU_ACPS_ARCACHE,
  input  [2:0]   PU_ACPS_ARPROT,
  input          PU_ACPS_RREADY,
  output         PU_ACPS_ARREADY,
  output         PU_ACPS_RVALID,
  output [P_AXI_ACP_ID_WIDTH-1:0]   PU_ACPS_RID,
  output [P_AXI_ACP_DATA_WIDTH-1:0] PU_ACPS_RDATA,
  output [1:0]   PU_ACPS_RRESP,
  output         PU_ACPS_RLAST,
  output         PU_ACPS_ARESETN,
  output         PU_ACPS_AWREADY,
  output         PU_ACPS_WREADY,
  output         PU_ACPS_BVALID,
  output [P_AXI_ACP_ID_WIDTH-1:0]   PU_ACPS_BID,
  output [1:0]   PU_ACPS_BRESP,

  input          PU_UPM0_CLK,
  input          PU_UPM0_ARREADY,
  input          PU_UPM0_AWREADY,
  input   [P_AXI_GP0_THREAD_ID_WIDTH-1:0] PU_UPM0_BID,
  input   [1:0]  PU_UPM0_BRESP,
  input          PU_UPM0_BVALID,
  input   [63:0] PU_UPM0_RDATA,
  input   [P_AXI_GP0_THREAD_ID_WIDTH-1:0] PU_UPM0_RID,
  input          PU_UPM0_RLAST,
  input   [1:0]  PU_UPM0_RRESP,
  input          PU_UPM0_RVALID,
  input          PU_UPM0_WREADY,
  output         PU_UPM0_RESETN,
  output  [31:0] PU_UPM0_ARADDR,
  output  [1:0]  PU_UPM0_ARBURST,
  output  [3:0]  PU_UPM0_ARCACHE,
  output  [P_AXI_GP0_THREAD_ID_WIDTH-1:0] PU_UPM0_ARID,
  output  [7:0]  PU_UPM0_ARLEN,
  output         PU_UPM0_ARLOCK,
  output  [2:0]  PU_UPM0_ARPROT,
  output  [2:0]  PU_UPM0_ARSIZE,
  output         PU_UPM0_ARVALID,
  output  [31:0] PU_UPM0_AWADDR,
  output  [1:0]  PU_UPM0_AWBURST,
  output  [3:0]  PU_UPM0_AWCACHE,
  output  [P_AXI_GP0_THREAD_ID_WIDTH-1:0] PU_UPM0_AWID,
  output  [7:0]  PU_UPM0_AWLEN,
  output         PU_UPM0_AWLOCK,
  output  [2:0]  PU_UPM0_AWPROT,
  output  [2:0]  PU_UPM0_AWSIZE,
  output         PU_UPM0_AWVALID,
  output         PU_UPM0_BREADY,
  output         PU_UPM0_RREADY,
  output  [63:0] PU_UPM0_WDATA,
  output         PU_UPM0_WLAST,
  output  [7:0]  PU_UPM0_WSTRB,
  output         PU_UPM0_WVALID,

  input          PU_UPM1_CLK,
  input          PU_UPM1_ARREADY,
  input          PU_UPM1_AWREADY,
  input   [P_AXI_GP1_THREAD_ID_WIDTH-1:0] PU_UPM1_BID,
  input   [1:0]  PU_UPM1_BRESP,
  input          PU_UPM1_BVALID,
  input   [63:0] PU_UPM1_RDATA,
  input   [P_AXI_GP1_THREAD_ID_WIDTH-1:0] PU_UPM1_RID,
  input          PU_UPM1_RLAST,
  input   [1:0]  PU_UPM1_RRESP,
  input          PU_UPM1_RVALID,
  input          PU_UPM1_WREADY,
  output         PU_UPM1_RESETN,
  output  [31:0] PU_UPM1_ARADDR,
  output  [1:0]  PU_UPM1_ARBURST,
  output  [3:0]  PU_UPM1_ARCACHE,
  output  [P_AXI_GP1_THREAD_ID_WIDTH-1:0] PU_UPM1_ARID,
  output  [7:0]  PU_UPM1_ARLEN,
  output         PU_UPM1_ARLOCK,
  output  [2:0]  PU_UPM1_ARPROT,
  output  [2:0]  PU_UPM1_ARSIZE,
  output         PU_UPM1_ARVALID,
  output  [31:0] PU_UPM1_AWADDR,
  output  [1:0]  PU_UPM1_AWBURST,
  output  [3:0]  PU_UPM1_AWCACHE,
  output  [P_AXI_GP1_THREAD_ID_WIDTH-1:0] PU_UPM1_AWID,
  output  [7:0]  PU_UPM1_AWLEN,
  output         PU_UPM1_AWLOCK,
  output  [2:0]  PU_UPM1_AWPROT,
  output  [2:0]  PU_UPM1_AWSIZE,
  output         PU_UPM1_AWVALID,
  output         PU_UPM1_BREADY,
  output         PU_UPM1_RREADY,
  output  [63:0] PU_UPM1_WDATA,
  output         PU_UPM1_WLAST,
  output  [7:0]  PU_UPM1_WSTRB,
  output         PU_UPM1_WVALID,

  input          PU_UPS0_CLK,
  input  [31:0]  PU_UPS0_ARADDR,
  input  [1:0]   PU_UPS0_ARBURST,
  input  [3:0]   PU_UPS0_ARCACHE,
  input  [(P_AXI_UPS0_ID_WIDTH - 1) : 0]   PU_UPS0_ARID,
  input  [7:0]   PU_UPS0_ARLEN,
  input          PU_UPS0_ARLOCK,
  input  [2:0]   PU_UPS0_ARPROT,
  input  [7:0]   PU_UPS0_WSTRB,
  input          PU_UPS0_WVALID,
  input  [2:0]   PU_UPS0_ARSIZE,
  input          PU_UPS0_ARVALID,
  input  [31:0]  PU_UPS0_AWADDR,
  input  [1:0]   PU_UPS0_AWBURST,
  input  [3:0]   PU_UPS0_AWCACHE,
  input  [(P_AXI_UPS0_ID_WIDTH - 1) : 0]   PU_UPS0_AWID,
  input  [7:0]   PU_UPS0_AWLEN,
  input          PU_UPS0_AWLOCK,
  input  [2:0]   PU_UPS0_AWPROT,
  input  [2:0]   PU_UPS0_AWSIZE,
  input          PU_UPS0_AWVALID,
  input          PU_UPS0_BREADY,
  input  [63:0]  PU_UPS0_WDATA,
  input          PU_UPS0_WLAST,
  input          PU_UPS0_RREADY,
  output [1:0]   PU_UPS0_BRESP,
  output         PU_UPS0_BVALID,
  output [63:0]  PU_UPS0_RDATA,
  output [(P_AXI_UPS0_ID_WIDTH - 1) : 0]   PU_UPS0_RID,
  output         PU_UPS0_RLAST,
  output [1:0]   PU_UPS0_RRESP,
  output         PU_UPS0_RVALID,
  output         PU_UPS0_WREADY,
  output         PU_UPS0_RESETN,
  output         PU_UPS0_ARREADY,
  output         PU_UPS0_AWREADY,
  output [(P_AXI_UPS0_ID_WIDTH - 1) : 0]   PU_UPS0_BID,

  input          PU_UPS1_CLK,
  input  [31:0]  PU_UPS1_ARADDR,
  input  [1:0]   PU_UPS1_ARBURST,
  input  [3:0]   PU_UPS1_ARCACHE,
  input  [(P_AXI_UPS1_ID_WIDTH - 1):0]   PU_UPS1_ARID,
  input  [7:0]   PU_UPS1_ARLEN,
  input          PU_UPS1_ARLOCK,
  input  [2:0]   PU_UPS1_ARPROT,
  input  [7:0]   PU_UPS1_WSTRB,
  input          PU_UPS1_WVALID,
  input  [2:0]   PU_UPS1_ARSIZE,
  input          PU_UPS1_ARVALID,
  input  [31:0]  PU_UPS1_AWADDR,
  input  [1:0]   PU_UPS1_AWBURST,
  input  [3:0]   PU_UPS1_AWCACHE,
  input  [(P_AXI_UPS1_ID_WIDTH - 1):0]   PU_UPS1_AWID,
  input  [7:0]   PU_UPS1_AWLEN,
  input          PU_UPS1_AWLOCK,
  input  [2:0]   PU_UPS1_AWPROT,
  input  [2:0]   PU_UPS1_AWSIZE,
  input          PU_UPS1_AWVALID,
  input          PU_UPS1_BREADY,
  input  [63:0]  PU_UPS1_WDATA,
  input          PU_UPS1_WLAST,
  input          PU_UPS1_RREADY,
  output [1:0]   PU_UPS1_BRESP,
  output         PU_UPS1_BVALID,
  output [63:0]  PU_UPS1_RDATA,
  output [(P_AXI_UPS1_ID_WIDTH - 1):0]   PU_UPS1_RID,
  output         PU_UPS1_RLAST,
  output [1:0]   PU_UPS1_RRESP,
  output         PU_UPS1_RVALID,
  output         PU_UPS1_WREADY,
  output         PU_UPS1_RESETN,
  output         PU_UPS1_ARREADY,
  output         PU_UPS1_AWREADY,
  output [(P_AXI_UPS1_ID_WIDTH - 1):0]   PU_UPS1_BID,

  input          PU_SPS0_CLK,
  input          PU_SPS0_AWVALID,
  input  [31:0]  PU_SPS0_AWADDR,
  input  [(P_AXI_HP0_ID_WIDTH - 1):0]   PU_SPS0_AWID,
  input  [7:0]   PU_SPS0_AWLEN,
  input  [2:0]   PU_SPS0_AWSIZE,
  input  [1:0]   PU_SPS0_AWBURST,
  input          PU_SPS0_AWLOCK,
  input  [3:0]   PU_SPS0_AWCACHE,
  input  [2:0]   PU_SPS0_AWPROT,
  input  [3:0]   PU_SPS0_AWQOS,
  input          PU_SPS0_RREADY,
  input          PU_SPS0_WVALID,
  input  [P_AXI_HP0_DATA_WIDTH-1:0]  PU_SPS0_WDATA,
  input  [P_AXI_HP0_DATA_WIDTH/8-1:0]  PU_SPS0_WSTRB,
  input          PU_SPS0_WLAST,
  input          PU_SPS0_BREADY,
  input          PU_SPS0_ARVALID,
  input  [(P_AXI_HP0_ID_WIDTH - 1):0]   PU_SPS0_ARID,
  input  [31:0]  PU_SPS0_ARADDR,
  input  [7:0]   PU_SPS0_ARLEN,
  input  [2:0]   PU_SPS0_ARSIZE,
  input  [1:0]   PU_SPS0_ARBURST,
  input          PU_SPS0_ARLOCK,
  input  [3:0]   PU_SPS0_ARCACHE,
  input  [2:0]   PU_SPS0_ARPROT,
  input  [3:0]   PU_SPS0_ARQOS,
  output         PU_SPS0_ARREADY,
  output         PU_SPS0_RVALID,
  output [(P_AXI_HP0_ID_WIDTH - 1):0]   PU_SPS0_RID,
  output [P_AXI_HP0_DATA_WIDTH-1:0]  PU_SPS0_RDATA,
  output [1:0]   PU_SPS0_RRESP,
  output         PU_SPS0_RLAST,
  output         PU_SPS0_RESETN,
  output         PU_SPS0_AWREADY,
  output         PU_SPS0_WREADY,
  output         PU_SPS0_BVALID,
  output [(P_AXI_HP0_ID_WIDTH - 1):0]   PU_SPS0_BID,
  output [1:0]   PU_SPS0_BRESP,

  input          PU_SPS1_CLK,
  input          PU_SPS1_AWVALID,
  input  [31:0]  PU_SPS1_AWADDR,
  input  [(P_AXI_HP1_ID_WIDTH - 1):0]   PU_SPS1_AWID,
  input  [7:0]   PU_SPS1_AWLEN,
  input  [2:0]   PU_SPS1_AWSIZE,
  input  [1:0]   PU_SPS1_AWBURST,
  input          PU_SPS1_AWLOCK,
  input  [3:0]   PU_SPS1_AWCACHE,
  input  [2:0]   PU_SPS1_AWPROT,
  input  [3:0]   PU_SPS1_AWQOS,
  input          PU_SPS1_RREADY,
  input          PU_SPS1_WVALID,
  input  [P_AXI_HP1_DATA_WIDTH-1:0]  PU_SPS1_WDATA,             
  input  [P_AXI_HP1_DATA_WIDTH/8-1:0]  PU_SPS1_WSTRB,
  input          PU_SPS1_WLAST,
  input          PU_SPS1_BREADY,
  input          PU_SPS1_ARVALID,
  input  [(P_AXI_HP1_ID_WIDTH - 1):0]   PU_SPS1_ARID,
  input  [31:0]  PU_SPS1_ARADDR,
  input  [7:0]   PU_SPS1_ARLEN,
  input  [2:0]   PU_SPS1_ARSIZE,
  input  [1:0]   PU_SPS1_ARBURST,
  input          PU_SPS1_ARLOCK,
  input  [3:0]   PU_SPS1_ARCACHE,
  input  [2:0]   PU_SPS1_ARPROT,
  input  [3:0]   PU_SPS1_ARQOS,
  output         PU_SPS1_ARREADY,
  output         PU_SPS1_RVALID,
  output [(P_AXI_HP1_ID_WIDTH - 1):0]   PU_SPS1_RID,
  output [P_AXI_HP1_DATA_WIDTH-1:0]  PU_SPS1_RDATA,
  output [1:0]   PU_SPS1_RRESP,
  output         PU_SPS1_RLAST,
  output         PU_SPS1_RESETN,
  output         PU_SPS1_AWREADY,
  output         PU_SPS1_WREADY,
  output         PU_SPS1_BVALID,
  output [(P_AXI_HP1_ID_WIDTH - 1):0]   PU_SPS1_BID,
  output [1:0]   PU_SPS1_BRESP,

  input          PU_SPS2_CLK,
  input          PU_SPS2_AWVALID,
  input  [31:0]  PU_SPS2_AWADDR,
  input  [(P_AXI_HP2_ID_WIDTH - 1):0]   PU_SPS2_AWID,
  input  [7:0]   PU_SPS2_AWLEN,
  input  [2:0]   PU_SPS2_AWSIZE,
  input  [1:0]   PU_SPS2_AWBURST,
  input          PU_SPS2_AWLOCK,
  input  [3:0]   PU_SPS2_AWCACHE,
  input  [2:0]   PU_SPS2_AWPROT,
  input  [3:0]   PU_SPS2_AWQOS,
  input          PU_SPS2_RREADY,
  input          PU_SPS2_WVALID,
  input  [P_AXI_HP2_DATA_WIDTH - 1:0]  PU_SPS2_WDATA,
  input  [7:0]   PU_SPS2_WSTRB,
  input          PU_SPS2_WLAST,
  input          PU_SPS2_BREADY,
  input          PU_SPS2_ARVALID,
  input  [(P_AXI_HP2_ID_WIDTH - 1):0]   PU_SPS2_ARID,
  input  [31:0]  PU_SPS2_ARADDR,
  input  [7:0]   PU_SPS2_ARLEN,
  input  [2:0]   PU_SPS2_ARSIZE,
  input  [1:0]   PU_SPS2_ARBURST,
  input          PU_SPS2_ARLOCK,
  input  [3:0]   PU_SPS2_ARCACHE,
  input  [2:0]   PU_SPS2_ARPROT,
  input  [3:0]   PU_SPS2_ARQOS,
  output         PU_SPS2_ARREADY,
  output         PU_SPS2_RVALID,
  output [(P_AXI_HP2_ID_WIDTH - 1):0]   PU_SPS2_RID,
  output [P_AXI_HP2_DATA_WIDTH - 1:0]  PU_SPS2_RDATA,
  output [1:0]   PU_SPS2_RRESP,
  output         PU_SPS2_RLAST,
  output         PU_SPS2_RESETN,
  output         PU_SPS2_AWREADY,
  output         PU_SPS2_WREADY,
  output         PU_SPS2_BVALID,
  output [(P_AXI_HP2_ID_WIDTH - 1):0]   PU_SPS2_BID,
  output [1:0]   PU_SPS2_BRESP,

  input          PU_SPS3_CLK,
  input          PU_SPS3_AWVALID,
  input  [31:0]  PU_SPS3_AWADDR,
  input  [(P_AXI_HP3_ID_WIDTH - 1):0]   PU_SPS3_AWID,
  input  [7:0]   PU_SPS3_AWLEN,
  input  [2:0]   PU_SPS3_AWSIZE,
  input  [1:0]   PU_SPS3_AWBURST,
  input          PU_SPS3_AWLOCK,
  input  [3:0]   PU_SPS3_AWCACHE,
  input  [2:0]   PU_SPS3_AWPROT,
  input  [3:0]   PU_SPS3_AWQOS,
  input          PU_SPS3_RREADY,
  input          PU_SPS3_WVALID,
  input  [P_AXI_HP3_DATA_WIDTH - 1:0]  PU_SPS3_WDATA,
  input  [7:0]   PU_SPS3_WSTRB,
  input          PU_SPS3_WLAST,
  input          PU_SPS3_BREADY,
  input          PU_SPS3_ARVALID,
  input  [(P_AXI_HP3_ID_WIDTH - 1):0]   PU_SPS3_ARID,
  input  [31:0]  PU_SPS3_ARADDR,
  input  [7:0]   PU_SPS3_ARLEN,
  input  [2:0]   PU_SPS3_ARSIZE,
  input  [1:0]   PU_SPS3_ARBURST,
  input          PU_SPS3_ARLOCK,
  input  [3:0]   PU_SPS3_ARCACHE,
  input  [2:0]   PU_SPS3_ARPROT,
  input  [3:0]   PU_SPS3_ARQOS,
  output         PU_SPS3_ARREADY,
  output         PU_SPS3_RVALID,
  output [(P_AXI_HP3_ID_WIDTH - 1):0]   PU_SPS3_RID,
  output [P_AXI_HP3_DATA_WIDTH - 1:0]  PU_SPS3_RDATA,
  output [1:0]   PU_SPS3_RRESP,
  output         PU_SPS3_RLAST,
  output         PU_SPS3_RESETN,
  output         PU_SPS3_AWREADY,
  output         PU_SPS3_WREADY,
  output         PU_SPS3_BVALID,
  output [(P_AXI_HP3_ID_WIDTH - 1):0]   PU_SPS3_BID,
  output [1:0]   PU_SPS3_BRESP,

  input          PU_AWURGENT0,
  input          PU_AWURGENT1,
  input          PU_AWURGENT2,
  input          PU_AWURGENT3,
  input          PU_ARURGENT0,
  input          PU_ARURGENT1,
  input          PU_ARURGENT2,
  input          PU_ARURGENT3,

  input          PU_DMA0_CLK,
  input          PU_DMA0_LAST,
  input          PU_DMA0_REQ,
  input          PU_DMA0_RESETN,
  input          PU_DMA0_SINGLE,
  output         PU_DMA0_ACK,
  output         PU_DMA0_FINISH,

  input          PU_DMA1_CLK,
  input          PU_DMA1_LAST,
  input          PU_DMA1_REQ,
  input          PU_DMA1_RESETN,
  input          PU_DMA1_SINGLE,
  output         PU_DMA1_ACK,
  output         PU_DMA1_FINISH,

  input          PU_DMA2_CLK,
  input          PU_DMA2_LAST,
  input          PU_DMA2_REQ,
  input          PU_DMA2_RESETN,
  input          PU_DMA2_SINGLE,
  output         PU_DMA2_ACK,
  output         PU_DMA2_FINISH,

  input          PU_DMA3_CLK,
  input          PU_DMA3_LAST,
  input          PU_DMA3_REQ,
  input          PU_DMA3_RESETN,
  input          PU_DMA3_SINGLE,
  output         PU_DMA3_ACK,
  output         PU_DMA3_FINISH,

  output         PU_IOMUX_CAN0_TXD,
  input          PU_IOMUX_CAN0_RXD,

  output         PU_IOMUX_CAN1_TXD,
  input          PU_IOMUX_CAN1_RXD,

  input          PU_IOMUX_ENET0_MD_I,
  input          PU_IOMUX_ENET0_COL,
  input          PU_IOMUX_ENET0_CRS,
  input          PU_IOMUX_ENET0_MIITXC,
  input          PU_IOMUX_ENET0_GMIIRXC,
  input          PU_IOMUX_ENET0_IRQF2P,
  input [7:0]    PU_IOMUX_ENET0_RXD,
  input          PU_IOMUX_ENET0_RXDV,
  input          PU_IOMUX_ENET0_RXER,
  input          PU_IOMUX_ENET0_AUX_TS_TRIG,
  input          PU_IOMUX_ENET0_MCG_PST_TRIG,
  input          PU_IOMUX_ENET0_MCGR_DMA_ACK,
  output         PU_IOMUX_ENET0_MCGR_DMA_REQ,
  output         PU_IOMUX_ENET0_PPS,
  output [79:0]  PU_IOMUX_ENET0_TIMESTAMP,
  output         PU_IOMUX_ENET0_MD_O,
  output         PU_IOMUX_ENET0_MD_TN,
  output         PU_IOMUX_ENET0_MDC,
  output [7:0]   PU_IOMUX_ENET0_TXD,
  output         PU_IOMUX_ENET0_TXEN,
  output         PU_IOMUX_ENET0_TXER,
  output         PU_IOMUX_ENET0_GMIITXC,

  input          PU_IOMUX_ENET1_MD_I,
  input          PU_IOMUX_ENET1_COL,
  input          PU_IOMUX_ENET1_CRS,
  input          PU_IOMUX_ENET1_MIITXC,
  input          PU_IOMUX_ENET1_GMIIRXC,
  input          PU_IOMUX_ENET1_IRQF2P,
  input [7:0]    PU_IOMUX_ENET1_RXD,
  input          PU_IOMUX_ENET1_RXDV,
  input          PU_IOMUX_ENET1_RXER,
  input          PU_IOMUX_ENET1_AUX_TS_TRIG,
  input          PU_IOMUX_ENET1_MCFG_DMA_ACK,
  input          PU_IOMUX_ENET1_MCG_PST_TRIG,
  output         PU_IOMUX_ENET1_MCFGR_DMA_REQ,
  output         PU_IOMUX_ENET1_PPS,
  output [79:0]  PU_IOMUX_ENET1_TIMESTAMP,
  output         PU_IOMUX_ENET1_MD_O,
  output         PU_IOMUX_ENET1_MD_TN,
  output         PU_IOMUX_ENET1_MDC,
  output [7:0]   PU_IOMUX_ENET1_TXD,
  output         PU_IOMUX_ENET1_TXEN,
  output         PU_IOMUX_ENET1_TXER,
  output         PU_IOMUX_ENET1_GMIITXC,

  output [P_EMIO_GPIO_WIDTH - 1:0] PU_IOMUX_GPIO_O,
  output [P_EMIO_GPIO_WIDTH - 1:0] PU_IOMUX_GPIO_TN,
  input  [P_EMIO_GPIO_WIDTH - 1:0] PU_IOMUX_GPIO_I,

  output         PU_IOMUX_I2C0_SCL_O,
  output         PU_IOMUX_I2C0_SCL_TN,
  input          PU_IOMUX_I2C0_SCL_I,
  output         PU_IOMUX_I2C0_SDA_O,
  output         PU_IOMUX_I2C0_SDA_TN,
  input          PU_IOMUX_I2C0_SDA_I,

  output         PU_IOMUX_I2C1_SCL_O,
  output         PU_IOMUX_I2C1_SCL_TN,
  input          PU_IOMUX_I2C1_SCL_I,
  output         PU_IOMUX_I2C1_SDA_O,
  output         PU_IOMUX_I2C1_SDA_TN,
  input          PU_IOMUX_I2C1_SDA_I,

  output         PU_IOMUX_PAJTAG_TDO,
  output         PU_IOMUX_PAJTAG_TDO_TN,
  input          PU_IOMUX_PAJTAG_TCK,
  input          PU_IOMUX_PAJTAG_TDI,
  input          PU_IOMUX_PAJTAG_TMS,

  output         PU_IOMUX_SDIO0_BUS_POW,
  output [2:0]   PU_IOMUX_SDIO0_BUS_VOLT,
  output         PU_IOMUX_SDIO0_CLK_O,
  input          PU_IOMUX_SDIO0_CMD_I,
  output         PU_IOMUX_SDIO0_CMD_O,
  output         PU_IOMUX_SDIO0_CMD_TN,
  input [3:0]    PU_IOMUX_SDIO0_DATA_I,
  output [3:0]   PU_IOMUX_SDIO0_DATA_O,
  output [3:0]   PU_IOMUX_SDIO0_DATA_TN,
  output         PU_IOMUX_SDIO0_LED,
  input          PU_IOMUX_SDIO0_CDN,
  input          PU_IOMUX_SDIO0_CLK_I,
  input          PU_IOMUX_SDIO0_WP,
  output         PU_IOMUX_SDIO0_RST_N,
  output         PU_IOMUX_SDIO0_RST_N_TN,

  output         PU_IOMUX_SDIO1_BUS_POW,
  output [2:0]   PU_IOMUX_SDIO1_BUS_VOLT,
  output         PU_IOMUX_SDIO1_CLK_O,
  input          PU_IOMUX_SDIO1_CMD_I,
  output         PU_IOMUX_SDIO1_CMD_O,
  output         PU_IOMUX_SDIO1_CMD_TN,
  input [3:0]    PU_IOMUX_SDIO1_DATA_I,
  output [3:0]   PU_IOMUX_SDIO1_DATA_O,
  output [3:0]   PU_IOMUX_SDIO1_DATA_TN,
  output         PU_IOMUX_SDIO1_LED,
  input          PU_IOMUX_SDIO1_CDN,
  input          PU_IOMUX_SDIO1_CLK_I,
  input          PU_IOMUX_SDIO1_WP,
  output         PU_IOMUX_SDIO1_RST_N,
  output         PU_IOMUX_SDIO1_RST_N_TN,

  output         PU_IOMUX_SPI0_MISO_O,
  output         PU_IOMUX_SPI0_MOSI_O,
  output         PU_IOMUX_SPI0_SCLK_O,
  input          PU_IOMUX_SPI0_MISO_I,
  input          PU_IOMUX_SPI0_MOSI_I,
  input          PU_IOMUX_SPI0_SCLK_I,
  input          PU_IOMUX_SPI0_SSN_I,
  output         PU_IOMUX_SPI0_MST_SSI_OE_N,
  output         PU_IOMUX_SPI0_SLV_SSI_OE_N,
  inout          PU_IOMUX_SPI0_SSN_O_0,
  output         PU_IOMUX_SPI0_SSN_O_1,
  output         PU_IOMUX_SPI0_SSN_O_2,

  output         PU_IOMUX_SPI1_MISO_O,
  output         PU_IOMUX_SPI1_MOSI_O,
  output         PU_IOMUX_SPI1_SCLK_O,
  input          PU_IOMUX_SPI1_MISO_I,
  input          PU_IOMUX_SPI1_MOSI_I,
  input          PU_IOMUX_SPI1_SCLK_I,
  input          PU_IOMUX_SPI1_SSN_I,
  output         PU_IOMUX_SPI1_MST_SSI_OE_N,
  output         PU_IOMUX_SPI1_SLV_SSI_OE_N,
  inout          PU_IOMUX_SPI1_SSN_O_0,
  output         PU_IOMUX_SPI1_SSN_O_1,
  output         PU_IOMUX_SPI1_SSN_O_2,

  output         PU_IOMUX_TRACE_CTL,
  output [P_EMIO_TRACE_WIDTH - 1:0]  PU_IOMUX_TRACE_DATA,
  output reg     PU_IOMUX_TRACE_CLKO,
  input          PU_IOMUX_TRACE_CLKI,

  output [2:0]   PU_IOMUX_TTC0_WAVEO,
  input  [2:0]   PU_IOMUX_TTC0_PAUSE,
  output [2:0]   PU_IOMUX_TTC1_WAVEO,	
  input  [2:0]   PU_IOMUX_TTC1_PAUSE,
  
  output         PU_IOMUX_UART0_DTR_N,
  output         PU_IOMUX_UART0_RTS_N,
  output         PU_IOMUX_UART0_TXD,
  input          PU_IOMUX_UART0_CTS_N,
  input          PU_IOMUX_UART0_DCD_N,
  input          PU_IOMUX_UART0_DSR_N,
  input          PU_IOMUX_UART0_RI_N,
  input          PU_IOMUX_UART0_RXD,

  output         PU_IOMUX_UART1_DTR_N,
  output         PU_IOMUX_UART1_RTS_N,
  output         PU_IOMUX_UART1_TXD,
  input          PU_IOMUX_UART1_CTS_N,
  input          PU_IOMUX_UART1_DCD_N,
  input          PU_IOMUX_UART1_DSR_N,
  input          PU_IOMUX_UART1_RI_N,
  input          PU_IOMUX_UART1_RXD,

  output         PU_IOMUX_WDT_RSTO,
  input          PU_IOMUX_WDT_PAUSE,

  input          PU_IOMUX_PA_IDLE_N,

  input          PU_IOMUX_EVENT_I,
  output         PU_IOMUX_EVENT_O,
  
  input  [P_F2P_INTR_INPUTS_NUM-1:0]  PU_IOMUX_IRQPA2PU,
  output         IRQ_P2F_GMAC0,
  output         IRQ_P2F_GMAC1,
  output         IRQ_P2F_SDIO0,
  output         IRQ_P2F_SDIO0_WAKEUP,
  output         IRQ_P2F_SDIO1,
  output         IRQ_P2F_SDIO1_WAKEUP,
  output         IRQ_P2F_USB2_0,
  output         IRQ_P2F_USB2_1,
  output         IRQ_P2F_CAN0,
  output         IRQ_P2F_CAN1,
  output         IRQ_P2F_DMAC,
  output         IRQ_P2F_GPIO,
  output         IRQ_P2F_I2C0,
  output         IRQ_P2F_I2C1,
  output         IRQ_P2F_OSPI,
  output         IRQ_P2F_SHANHAI_N,
  output         IRQ_P2F_SHANHAI_S,
  output         IRQ_P2F_SSI0,
  output         IRQ_P2F_SSI1,
  output         IRQ_P2F_TIMER0,
  output         IRQ_P2F_TIMER1,
  output         IRQ_P2F_UART0,
  output         IRQ_P2F_UART1,
  output         IRQ_P2F_WDT,

  output [1:0]   PU_IOMUX_STANDBY_WFE,
  output [1:0]   PU_IOMUX_STANDBY_WFI,

  input  [3:0]   PU_IOMUX_PATMDTRACEINATID,
  input          PU_IOMUX_PATMDTRACEINCLOCK,
  input  [31:0]  PU_IOMUX_PATMDTRACEINDATA,
  input          PU_IOMUX_PATMDTRACEINVALID,

  input  [31:0]  PU_IOMUX_PATMTPA2PUDDEBUG,
  output [31:0]  PU_IOMUX_PATMTPU2PADDEBUG,

  input  [3:0]   PU_IOMUX_PATMTPA2PUTRIG,
  output [3:0]   PU_IOMUX_PATMTPU2PATRIG,
  output [3:0]   PU_IOMUX_PATMTPA2PUTRIGACK,
  input  [3:0]   PU_IOMUX_PATMTPU2PATRIGACK,

  input          PU_IOMUX_ENET_PTP_REF,

  input          PU_PACLK0_CLK_TRIG_N,
  input          PU_PACLK1_CLK_TRIG_N,
  input          PU_PACLK2_CLK_TRIG_N,
  input          PU_PACLK3_CLK_TRIG_N,

  output         PU_IOMUX_PACLK0_RESETN,
  output         PU_IOMUX_PACLK1_RESETN,
  output         PU_IOMUX_PACLK2_RESETN,
  output         PU_IOMUX_PACLK3_RESETN,

  output         PU_IOMUX_PACLK3,
  output         PU_IOMUX_PACLK2,
  output         PU_IOMUX_PACLK1,
  output         PU_IOMUX_PACLK0
);

wire [11:0]  PU_UPM0_AWID_FULL;
wire [11:0]  PU_UPM0_ARID_FULL;
wire [11:0]  PU_UPM0_BID_FULL;
wire [11:0]  PU_UPM0_RID_FULL;

wire [11:0]  PU_UPM1_AWID_FULL;
wire [11:0]  PU_UPM1_WID_FULL;
wire [11:0]  PU_UPM1_ARID_FULL;
wire [11:0]  PU_UPM1_BID_FULL;
wire [11:0]  PU_UPM1_RID_FULL;

function [5:0] compress_id;
    input [11:0] id;
    begin
        case(id)
            //CPU
            12'b000000000001 : compress_id = 6'd0;
            12'b000000000011 : compress_id = 6'd1;
            12'b000000001001 : compress_id = 6'd2;
            12'b000000001011 : compress_id = 6'd3;
            12'b000000010011 : compress_id = 6'd4;
            12'b000000011001 : compress_id = 6'd5;
            12'b000000011011 : compress_id = 6'd6;
            12'b000000100001 : compress_id = 6'd7;
            12'b000000100011 : compress_id = 6'd8;
            12'b000000100101 : compress_id = 6'd9;
            12'b000000100111 : compress_id = 6'd10;
            12'b000000101001 : compress_id = 6'd11;
            12'b000000101011 : compress_id = 6'd12;
            12'b000000101101 : compress_id = 6'd13;
            12'b000000101111 : compress_id = 6'd14;
            12'b000000110001 : compress_id = 6'd15;
            12'b000000110011 : compress_id = 6'd16;
            12'b000000110101 : compress_id = 6'd17;
            12'b000000110111 : compress_id = 6'd18;
            12'b000000111001 : compress_id = 6'd19;
            12'b000000111011 : compress_id = 6'd20;
            12'b000000111101 : compress_id = 6'd21;
            12'b000000111111 : compress_id = 6'd22;
            12'b000001000001 : compress_id = 6'd23;
            12'b000001001001 : compress_id = 6'd24;
            12'b000001010001 : compress_id = 6'd25;
            12'b000001011001 : compress_id = 6'd26;
            12'b000001100001 : compress_id = 6'd27;
            12'b000001101001 : compress_id = 6'd28;
            12'b000001110001 : compress_id = 6'd29;
            12'b000001111001 : compress_id = 6'd30;
            12'b000001000011 : compress_id = 6'd31;
            12'b000001001011 : compress_id = 6'd32;
            12'b000001010011 : compress_id = 6'd33;
            12'b000001011011 : compress_id = 6'd34;
            12'b000001100011 : compress_id = 6'd35;
            12'b000001101011 : compress_id = 6'd36;
            12'b000001110011 : compress_id = 6'd37;
            12'b000001111011 : compress_id = 6'd38;
            //DMA
            12'b000000000010 : compress_id = 6'd39;
            12'b000000001010 : compress_id = 6'd40;
            12'b000000010010 : compress_id = 6'd41;
            12'b000000011010 : compress_id = 6'd42;
            12'b000000100010 : compress_id = 6'd43;
            12'b000000101010 : compress_id = 6'd44;
            12'b000000110010 : compress_id = 6'd45;
            12'b000000111010 : compress_id = 6'd46;
            12'b000001000010 : compress_id = 6'd47;
            12'b000001001010 : compress_id = 6'd48;
            12'b000001010010 : compress_id = 6'd49;
            12'b000001011010 : compress_id = 6'd50;
            12'b000001100010 : compress_id = 6'd51;
            12'b000001101010 : compress_id = 6'd52;
            12'b000001110010 : compress_id = 6'd53;
            12'b000001111010 : compress_id = 6'd54;
            //USB2_0
            12'b000001000000 : compress_id = 6'd55;
            //USB2_1
            12'b000001010000 : compress_id = 6'd56;
            //GMAC_0
            12'b000000001000 : compress_id = 6'd57;
            12'b000010001000 : compress_id = 6'd58;
            //GMAC_1
            12'b000000000000 : compress_id = 6'd59;
            12'b000010000000 : compress_id = 6'd60;
            //SDIO_0
            12'b000001100000 : compress_id = 6'd61;
            //SDIO_1
            12'b000001001000 : compress_id = 6'd62;
            //AHB-AP
            12'b000000100100 : compress_id = 6'd63;
            default: compress_id = 6'b111111;
        endcase
    end
endfunction

function [11:0] uncompress_id;
    input [5:0] id;
        begin
            case(id[5:0])
            //CPU
            6'd0  : uncompress_id = 12'b000000000001 ;
            6'd1  : uncompress_id = 12'b000000000011 ;
            6'd2  : uncompress_id = 12'b000000001001 ;
            6'd3  : uncompress_id = 12'b000000001011 ;
            6'd4  : uncompress_id = 12'b000000010011 ;
            6'd5  : uncompress_id = 12'b000000011001 ;
            6'd6  : uncompress_id = 12'b000000011011 ;
            6'd7  : uncompress_id = 12'b000000100001 ;
            6'd8  : uncompress_id = 12'b000000100011 ;
            6'd9  : uncompress_id = 12'b000000100101 ;
            6'd10 : uncompress_id = 12'b000000100111 ;
            6'd11 : uncompress_id = 12'b000000101001 ;
            6'd12 : uncompress_id = 12'b000000101011 ;
            6'd13 : uncompress_id = 12'b000000101101 ;
            6'd14 : uncompress_id = 12'b000000101111 ;
            6'd15 : uncompress_id = 12'b000000110001 ;
            6'd16 : uncompress_id = 12'b000000110011 ;
            6'd17 : uncompress_id = 12'b000000110101 ;
            6'd18 : uncompress_id = 12'b000000110111 ;
            6'd19 : uncompress_id = 12'b000000111001 ;
            6'd20 : uncompress_id = 12'b000000111011 ;
            6'd21 : uncompress_id = 12'b000000111101 ;
            6'd22 : uncompress_id = 12'b000000111111 ;
            6'd23 : uncompress_id = 12'b000001000001 ;
            6'd24 : uncompress_id = 12'b000001001001 ;
            6'd25 : uncompress_id = 12'b000001010001 ;
            6'd26 : uncompress_id = 12'b000001011001 ;
            6'd27 : uncompress_id = 12'b000001100001 ;
            6'd28 : uncompress_id = 12'b000001101001 ;
            6'd29 : uncompress_id = 12'b000001110001 ;
            6'd30 : uncompress_id = 12'b000001111001 ;
            6'd31 : uncompress_id = 12'b000001000011 ;
            6'd32 : uncompress_id = 12'b000001001011 ;
            6'd33 : uncompress_id = 12'b000001010011 ;
            6'd34 : uncompress_id = 12'b000001011011 ;
            6'd35 : uncompress_id = 12'b000001100011 ;
            6'd36 : uncompress_id = 12'b000001101011 ;
            6'd37 : uncompress_id = 12'b000001110011 ;
            6'd38 : uncompress_id = 12'b000001111011 ;
            //DMA 
            6'd39 : uncompress_id = 12'b000000000010 ;
            6'd40 : uncompress_id = 12'b000000001010 ;
            6'd41 : uncompress_id = 12'b000000010010 ;
            6'd42 : uncompress_id = 12'b000000011010 ;
            6'd43 : uncompress_id = 12'b000000100010 ;
            6'd44 : uncompress_id = 12'b000000101010 ;
            6'd45 : uncompress_id = 12'b000000110010 ;
            6'd46 : uncompress_id = 12'b000000111010 ;
            6'd47 : uncompress_id = 12'b000001000010 ;
            6'd48 : uncompress_id = 12'b000001001010 ;
            6'd49 : uncompress_id = 12'b000001010010 ;
            6'd50 : uncompress_id = 12'b000001011010 ;
            6'd51 : uncompress_id = 12'b000001100010 ;
            6'd52 : uncompress_id = 12'b000001101010 ;
            6'd53 : uncompress_id = 12'b000001110010 ;
            6'd54 : uncompress_id = 12'b000001111010 ;
            //USB2_0
            6'd55 : uncompress_id = 12'b000001000000 ;
            //USB2_1
            6'd56 : uncompress_id = 12'b000001010000 ;
            //GMAC_0
            6'd57 : uncompress_id = 12'b000000001000 ;
            6'd58 : uncompress_id = 12'b000010001000 ;
            //GMAC_1
            6'd59 : uncompress_id = 12'b000000000000 ;
            6'd60 : uncompress_id = 12'b000010000000 ;
            //SDIO_0
            6'd61 : uncompress_id = 12'b000001100000 ;
            //SDIO_1
            6'd62 : uncompress_id = 12'b000001001000 ;
            //AHB-AP
            6'd63 : uncompress_id = 12'b000000100100 ;
            default : uncompress_id = 12'b000000000000;
        endcase
    end
endfunction

	assign PU_UPM0_AWID        = (P_AXI_GP0_ENABLE_STATIC_REMAP == 1) ? compress_id(PU_UPM0_AWID_FULL) : PU_UPM0_AWID_FULL;   
	assign PU_UPM0_ARID        = (P_AXI_GP0_ENABLE_STATIC_REMAP == 1) ? compress_id(PU_UPM0_ARID_FULL) : PU_UPM0_ARID_FULL;      
	assign PU_UPM0_BID_FULL    = (P_AXI_GP0_ENABLE_STATIC_REMAP == 1) ? uncompress_id(PU_UPM0_BID)     : PU_UPM0_BID;
	assign PU_UPM0_RID_FULL    = (P_AXI_GP0_ENABLE_STATIC_REMAP == 1) ? uncompress_id(PU_UPM0_RID)     : PU_UPM0_RID;      

	assign PU_UPM1_AWID        = (P_AXI_GP1_ENABLE_STATIC_REMAP == 1) ? compress_id(PU_UPM1_AWID_FULL) : PU_UPM1_AWID_FULL;
	assign PU_UPM1_ARID        = (P_AXI_GP1_ENABLE_STATIC_REMAP == 1) ? compress_id(PU_UPM1_ARID_FULL) : PU_UPM1_ARID_FULL;      
	assign PU_UPM1_BID_FULL    = (P_AXI_GP1_ENABLE_STATIC_REMAP == 1) ? uncompress_id(PU_UPM1_BID)     : PU_UPM1_BID;
	assign PU_UPM1_RID_FULL    = (P_AXI_GP1_ENABLE_STATIC_REMAP == 1) ? uncompress_id(PU_UPM1_RID)     : PU_UPM1_RID;     

//interrupt
wire [19:0] pu_irqpa2pu;
assign pu_irqpa2pu = (P_F2P_INTR_INPUTS_NUM == 20) ? PU_IOMUX_IRQPA2PU[P_F2P_INTR_INPUTS_NUM-1:0] : {{(20-P_F2P_INTR_INPUTS_NUM){0}},PU_IOMUX_IRQPA2PU[P_F2P_INTR_INPUTS_NUM-1:0]};

wire [27:0] pu_irqpu2pa;
assign IRQ_P2F_GMAC0 = pu_irqpu2pa[27];
assign IRQ_P2F_GMAC1 = pu_irqpu2pa[24];
assign IRQ_P2F_SDIO0 = pu_irqpu2pa[21];
assign IRQ_P2F_SDIO0_WAKEUP = pu_irqpu2pa[20];
assign IRQ_P2F_SDIO1 = pu_irqpu2pa[19];
assign IRQ_P2F_SDIO1_WAKEUP = pu_irqpu2pa[18];
assign IRQ_P2F_USB2_0 = pu_irqpu2pa[17];
assign IRQ_P2F_USB2_1 = pu_irqpu2pa[16];
assign IRQ_P2F_CAN0 = pu_irqpu2pa[15];
assign IRQ_P2F_CAN1 = pu_irqpu2pa[14];
assign IRQ_P2F_DMAC = pu_irqpu2pa[13];
assign IRQ_P2F_GPIO = pu_irqpu2pa[12];
assign IRQ_P2F_I2C0 = pu_irqpu2pa[11];
assign IRQ_P2F_I2C1 = pu_irqpu2pa[10];
assign IRQ_P2F_OSPI = pu_irqpu2pa[9];
assign IRQ_P2F_SHANHAI_N = pu_irqpu2pa[8];
assign IRQ_P2F_SHANHAI_S = pu_irqpu2pa[7];
assign IRQ_P2F_SSI0 = pu_irqpu2pa[6];
assign IRQ_P2F_SSI1 = pu_irqpu2pa[5];
assign IRQ_P2F_TIMER0 = pu_irqpu2pa[4];
assign IRQ_P2F_TIMER1 = pu_irqpu2pa[3];
assign IRQ_P2F_UART0 = pu_irqpu2pa[2];
assign IRQ_P2F_UART1 = pu_irqpu2pa[1];
assign IRQ_P2F_WDT = pu_irqpu2pa[0];

//GPIO
wire [63:0] ntPU_IOMUX_GPIO_O;
wire [63:0] ntPU_IOMUX_GPIO_I;
wire [63:0] ntPU_IOMUX_GPIO_TN;
assign PU_IOMUX_GPIO_O = ntPU_IOMUX_GPIO_O[P_EMIO_GPIO_WIDTH - 1:0];
assign PU_IOMUX_GPIO_TN = ntPU_IOMUX_GPIO_TN[P_EMIO_GPIO_WIDTH - 1:0];
assign ntPU_IOMUX_GPIO_I = (P_EMIO_GPIO_WIDTH == 64) ? PU_IOMUX_GPIO_I : {{(64 - P_EMIO_GPIO_WIDTH){0}},PU_IOMUX_GPIO_I};

// FCLK_CLK optional clock buffers
wire    [3:0] FCLK_CLK_unbuffered;
wire    [3:0] FCLK_CLK_buffered;
wire          PU_IOMUX_PACLK0_temp;

generate
   if (P_FCLK_CLK0_BUF == "TRUE" | P_FCLK_CLK0_BUF == "true") begin : buffer_fclk_clk_0
     GTP_CLKBUFG FCLK_CLK_0_BUFG (.CLKIN(FCLK_CLK_unbuffered[0]), .CLKOUT(FCLK_CLK_buffered[0]));
   end
   if (P_FCLK_CLK1_BUF == "TRUE" | P_FCLK_CLK1_BUF == "true") begin : buffer_fclk_clk_1
     GTP_CLKBUFG FCLK_CLK_1_BUFG (.CLKIN(FCLK_CLK_unbuffered[1]), .CLKOUT(FCLK_CLK_buffered[1]));
   end
   if (P_FCLK_CLK2_BUF == "TRUE" | P_FCLK_CLK2_BUF == "true") begin : buffer_fclk_clk_2
     GTP_CLKBUFG FCLK_CLK_2_BUFG (.CLKIN(FCLK_CLK_unbuffered[2]), .CLKOUT(FCLK_CLK_buffered[2]));
   end
   if (P_FCLK_CLK3_BUF == "TRUE" | P_FCLK_CLK3_BUF == "true") begin : buffer_fclk_clk_3
     GTP_CLKBUFG FCLK_CLK_3_BUFG (.CLKIN(FCLK_CLK_unbuffered[3]), .CLKOUT(FCLK_CLK_buffered[3]));
   end
endgenerate 

assign PU_IOMUX_PACLK0_temp = (P_FCLK_CLK0_BUF == "TRUE" | P_FCLK_CLK0_BUF == "true") ? FCLK_CLK_buffered[0] : FCLK_CLK_unbuffered[0];
assign PU_IOMUX_PACLK1 = (P_FCLK_CLK1_BUF == "TRUE" | P_FCLK_CLK1_BUF == "true") ? FCLK_CLK_buffered[1] : FCLK_CLK_unbuffered[1];
assign PU_IOMUX_PACLK2 = (P_FCLK_CLK2_BUF == "TRUE" | P_FCLK_CLK2_BUF == "true") ? FCLK_CLK_buffered[2] : FCLK_CLK_unbuffered[2];
assign PU_IOMUX_PACLK3 = (P_FCLK_CLK3_BUF == "TRUE" | P_FCLK_CLK3_BUF == "true") ? FCLK_CLK_buffered[3] : FCLK_CLK_unbuffered[3];

assign PU_IOMUX_PACLK0 = PU_IOMUX_PACLK0_temp;

//Connect FCLK in case of disable the AXI port for non Secure Transaction
wire S_AXI_SPS0_ACLK_temp;
wire S_AXI_SPS1_ACLK_temp;
wire S_AXI_SPS2_ACLK_temp;
wire S_AXI_SPS3_ACLK_temp;
wire M_AXI_UPM0_ACLK_temp;
wire M_AXI_UPM1_ACLK_temp;
wire S_AXI_UPS0_ACLK_temp;
wire S_AXI_UPS1_ACLK_temp;
wire S_AXI_ACP_ACLK_temp;

generate
  if ( P_USE_AXI_NONSECURE == 1 && P_USE_S_AXI_HP0 == 0) begin 
   assign S_AXI_SPS0_ACLK_temp = PU_IOMUX_PACLK0_temp;
  end
  else begin
  assign S_AXI_SPS0_ACLK_temp = PU_SPS0_CLK;
  end
endgenerate

generate
  if ( P_USE_AXI_NONSECURE == 1 && P_USE_S_AXI_HP1 == 0) begin 
	assign S_AXI_SPS1_ACLK_temp = PU_IOMUX_PACLK0_temp;
  end
  else begin
	assign S_AXI_SPS1_ACLK_temp = PU_SPS1_CLK;
  end
endgenerate

generate
  if ( P_USE_AXI_NONSECURE == 1 && P_USE_S_AXI_HP2 == 0) begin 
	assign S_AXI_SPS2_ACLK_temp = PU_IOMUX_PACLK0_temp;
  end
  else begin
	assign S_AXI_SPS2_ACLK_temp = PU_SPS2_CLK;
  end
endgenerate

generate
  if ( P_USE_AXI_NONSECURE == 1 && P_USE_S_AXI_HP3 == 0) begin 
	assign S_AXI_SPS3_ACLK_temp = PU_IOMUX_PACLK0_temp;
  end
  else begin
	assign S_AXI_SPS3_ACLK_temp = PU_SPS3_CLK;
  end
endgenerate

generate
  if ( P_USE_AXI_NONSECURE == 1 && P_USE_M_AXI_GP0 == 0) begin 
	assign M_AXI_UPM0_ACLK_temp = PU_IOMUX_PACLK0_temp;
  end
  else begin
	assign M_AXI_UPM0_ACLK_temp = PU_UPM0_CLK;  
  end
endgenerate

generate
  if ( P_USE_AXI_NONSECURE == 1 && P_USE_M_AXI_GP1 == 0) begin 
	assign M_AXI_UPM1_ACLK_temp = PU_IOMUX_PACLK0_temp;
  end
  else begin
	assign M_AXI_UPM1_ACLK_temp = PU_UPM1_CLK;    
  end
endgenerate

generate
  if ( P_USE_AXI_NONSECURE == 1 && P_USE_S_AXI_GP0 == 0) begin 
	assign S_AXI_UPS0_ACLK_temp = PU_IOMUX_PACLK0_temp;
  end
  else begin
	assign S_AXI_UPS0_ACLK_temp = PU_UPS0_CLK;    
    end
endgenerate

generate
  if ( P_USE_AXI_NONSECURE == 1 && P_USE_S_AXI_GP1 == 0) begin 
	assign S_AXI_UPS1_ACLK_temp = PU_IOMUX_PACLK0_temp;
  end
  else begin
	assign S_AXI_UPS1_ACLK_temp = PU_UPS1_CLK;      
   end
endgenerate

generate
  if ( P_USE_AXI_NONSECURE == 1 && P_USE_S_AXI_ACP == 0) begin 
	assign S_AXI_ACP_ACLK_temp = PU_IOMUX_PACLK0_temp;
  end
  else begin
	assign S_AXI_ACP_ACLK_temp = PU_ACPS_ACLK;        
  end
endgenerate


//EMIO trace
wire [31:0] TRACE_DATA;
wire TRACE_CTL;
reg  TRACE_CTL_PIPE [(P_TRACE_PIPELINE_WIDTH - 1):0];
reg  [(P_EMIO_TRACE_WIDTH)-1:0] TRACE_DATA_PIPE [(P_TRACE_PIPELINE_WIDTH - 1):0];

integer j;
generate
  if (P_ENABLE_EMIO_TRACE == 1) begin 
    always @(posedge PU_IOMUX_TRACE_CLKI) 
    begin
	  TRACE_CTL_PIPE[P_TRACE_PIPELINE_WIDTH - 1] <= TRACE_CTL;
	  TRACE_DATA_PIPE[P_TRACE_PIPELINE_WIDTH - 1] <= TRACE_DATA[(P_EMIO_TRACE_WIDTH-1):0];
	  for (j=(P_TRACE_PIPELINE_WIDTH-1); j>0; j=j-1) begin
		TRACE_CTL_PIPE[j-1] <= TRACE_CTL_PIPE[j];
		TRACE_DATA_PIPE[j-1] <= TRACE_DATA_PIPE[j];
      end
	  PU_IOMUX_TRACE_CLKO  <= ~PU_IOMUX_TRACE_CLKO;
	end
  end	
else
begin
always @*
begin
  TRACE_CTL_PIPE[P_TRACE_PIPELINE_WIDTH - 1] <= 1'b0;
  TRACE_DATA_PIPE[P_TRACE_PIPELINE_WIDTH - 1] <= 1'b0; 
  for (j=(P_TRACE_PIPELINE_WIDTH-1); j>0; j=j-1) begin
    TRACE_CTL_PIPE[j-1] <= 1'b0;
    TRACE_DATA_PIPE[j-1] <= 1'b0;
  end
  PU_IOMUX_TRACE_CLKO  <= 1'b0; 
end
end
endgenerate

assign PU_IOMUX_TRACE_CTL = TRACE_CTL_PIPE[0];
assign PU_IOMUX_TRACE_DATA = TRACE_DATA_PIPE[0];

reg    [31:0] FTMD_TRACEIN_DATA_notracebuf;
reg           FTMD_TRACEIN_VALID_notracebuf;
reg    [3:0]  FTMD_TRACEIN_ATID_notracebuf;

wire   [31:0] FTMD_TRACEIN_DATA_tracebuf;
wire          FTMD_TRACEIN_VALID_tracebuf;
wire   [3:0]  FTMD_TRACEIN_ATID_tracebuf;

wire   [31:0] FTMD_TRACEIN_DATA;
wire          FTMD_TRACEIN_VALID;
wire   [3:0]  FTMD_TRACEIN_ATID;

generate
  if (P_GENERATE_FIFO == 0) begin : gen_no_trace_buffer
    always @(posedge PU_IOMUX_PATMDTRACEINCLOCK) 
    begin
      FTMD_TRACEIN_DATA_notracebuf    <= PU_IOMUX_PATMDTRACEINDATA;
      FTMD_TRACEIN_VALID_notracebuf   <= PU_IOMUX_PATMDTRACEINVALID;
      FTMD_TRACEIN_ATID_notracebuf    <= PU_IOMUX_PATMDTRACEINATID;
    end

    assign FTMD_TRACEIN_DATA   = FTMD_TRACEIN_DATA_notracebuf;
    assign FTMD_TRACEIN_VALID  = FTMD_TRACEIN_VALID_notracebuf;
    assign FTMD_TRACEIN_ATID   = FTMD_TRACEIN_ATID_notracebuf;

  end else begin : gen_trace_buffer
  
    pu_trace_buffer #(
      .FIFO_SIZE (P_TRACE_BUFFER_FIFO_SIZE),
      .USE_TRACE_DATA_EDGE_DETECTOR(P_TRACE_DATA_EDGE_DETECTOR),
      .C_DELAY_CLKS(P_TRACE_BUFFER_CLOCK_DELAY)
     ) trace_buffer_i (
      .TRACE_CLK(PU_IOMUX_PATMDTRACEINCLOCK), 
      .RST(~PU_IOMUX_PACLK0_RESETN), 
      .TRACE_VALID_IN(PU_IOMUX_PATMDTRACEINVALID), 
      .TRACE_DATA_IN(PU_IOMUX_PATMDTRACEINDATA), 
      .TRACE_ATID_IN(PU_IOMUX_PATMDTRACEINATID), 
      .TRACE_ATID_OUT(FTMD_TRACEIN_ATID_tracebuf), 
      .TRACE_VALID_OUT(FTMD_TRACEIN_VALID_tracebuf), 
      .TRACE_DATA_OUT(FTMD_TRACEIN_DATA_tracebuf)
    );

    assign FTMD_TRACEIN_DATA   = FTMD_TRACEIN_DATA_tracebuf;
    assign FTMD_TRACEIN_VALID  = FTMD_TRACEIN_VALID_tracebuf;
    assign FTMD_TRACEIN_ATID   = FTMD_TRACEIN_ATID_tracebuf;
 
  end
endgenerate

wire [5:0]    PU_UPS0_BID_out;
wire [5:0]    PU_UPS0_RID_out;
wire [5:0]    PU_UPS0_ARID_in;
wire [5:0]    PU_UPS0_AWID_in;

wire [5:0]    PU_UPS1_BID_out;
wire [5:0]    PU_UPS1_RID_out;
wire [5:0]    PU_UPS1_ARID_in;
wire [5:0]    PU_UPS1_AWID_in;

wire [3:0]    PU_SPS0_BID_out;
wire [3:0]    PU_SPS0_RID_out;
wire [3:0]    PU_SPS0_ARID_in;
wire [3:0]    PU_SPS0_AWID_in;

wire [3:0]    PU_SPS1_BID_out;
wire [3:0]    PU_SPS1_RID_out;
wire [3:0]    PU_SPS1_ARID_in;
wire [3:0]    PU_SPS1_AWID_in;

wire [3:0]    PU_SPS2_BID_out;
wire [3:0]    PU_SPS2_RID_out;
wire [3:0]    PU_SPS2_ARID_in;
wire [3:0]    PU_SPS2_AWID_in;

wire [3:0]    PU_SPS3_BID_out;
wire [3:0]    PU_SPS3_RID_out;
wire [3:0]    PU_SPS3_ARID_in;
wire [3:0]    PU_SPS3_AWID_in;

wire [4:0]    PU_ACPS_BID_out;
wire [4:0]    PU_ACPS_RID_out;
wire [4:0]    PU_ACPS_ARID_in;
wire [4:0]    PU_ACPS_AWID_in;
wire [4:0]    PU_ACPS_WID_in;  

wire [(P_AXI_ACP_ID_WIDTH - 1) : 0]    S_AXI_ACP_BID_W;
wire [(P_AXI_ACP_ID_WIDTH - 1) : 0]    S_AXI_ACP_RID_W;
wire [(P_AXI_ACP_ID_WIDTH - 1) : 0]    S_AXI_ACP_ARID_W;
wire [(P_AXI_ACP_ID_WIDTH - 1) : 0]    S_AXI_ACP_AWID_W;
wire [(P_AXI_ACP_ID_WIDTH - 1) : 0]    S_AXI_ACP_WID_W; 

   // ID Width Control on AXI Slave ports
   // S_AXI_GP0
	function [5:0] id_in_gp0;
	   input [(P_AXI_UPS0_ID_WIDTH - 1) : 0] axi_id_gp0_in;
	begin
		case (P_AXI_UPS0_ID_WIDTH)
			  1:  id_in_gp0  = {5'b0, axi_id_gp0_in};
			  2:  id_in_gp0  = {4'b0, axi_id_gp0_in};
			  3:  id_in_gp0  = {3'b0, axi_id_gp0_in};
			  4:  id_in_gp0  = {2'b0, axi_id_gp0_in};
			  5:  id_in_gp0  = {1'b0, axi_id_gp0_in};
			  6:  id_in_gp0  = axi_id_gp0_in;    
			  default : id_in_gp0 =  axi_id_gp0_in;
		endcase
	end
	endfunction

    assign PU_UPS0_ARID_in = id_in_gp0(PU_UPS0_ARID);
    assign PU_UPS0_AWID_in = id_in_gp0(PU_UPS0_AWID);

     function [5:0] id_out_gp0;
       input [(P_AXI_UPS0_ID_WIDTH - 1) : 0] axi_id_gp0_out;
     begin
        case (P_AXI_UPS0_ID_WIDTH)
              1:  id_out_gp0  = axi_id_gp0_out[0];
              2:  id_out_gp0  = axi_id_gp0_out[1:0];
              3:  id_out_gp0  = axi_id_gp0_out[2:0];
              4:  id_out_gp0  = axi_id_gp0_out[3:0];
              5:  id_out_gp0  = axi_id_gp0_out[4:0];
              6:  id_out_gp0  = axi_id_gp0_out;    
              default : id_out_gp0 =  axi_id_gp0_out;              
        endcase
     end
     endfunction
    
    assign PU_UPS0_BID     = id_out_gp0(PU_UPS0_BID_out);
    assign PU_UPS0_RID     = id_out_gp0(PU_UPS0_RID_out);    
   
    // S_AXI_GP1
   
    function [5:0] id_in_gp1;
       input [(P_AXI_UPS1_ID_WIDTH - 1) : 0] axi_id_gp1_in;
    begin
        case (P_AXI_UPS1_ID_WIDTH)
              1:  id_in_gp1  = {5'b0, axi_id_gp1_in};
              2:  id_in_gp1  = {4'b0, axi_id_gp1_in};
              3:  id_in_gp1  = {3'b0, axi_id_gp1_in};
              4:  id_in_gp1  = {2'b0, axi_id_gp1_in};
              5:  id_in_gp1  = {1'b0, axi_id_gp1_in};
              6:  id_in_gp1  = axi_id_gp1_in;    
              default : id_in_gp1 =  axi_id_gp1_in;
        endcase
    end
    endfunction

    assign PU_UPS1_ARID_in = id_in_gp1(PU_UPS1_ARID);
    assign PU_UPS1_AWID_in = id_in_gp1(PU_UPS1_AWID);

    function [5:0] id_out_gp1;
       input [(P_AXI_UPS1_ID_WIDTH - 1) : 0] axi_id_gp1_out;
    begin
        case (P_AXI_UPS1_ID_WIDTH)
              1:  id_out_gp1  = axi_id_gp1_out[0];
              2:  id_out_gp1  = axi_id_gp1_out[1:0];
              3:  id_out_gp1  = axi_id_gp1_out[2:0];
              4:  id_out_gp1  = axi_id_gp1_out[3:0];
              5:  id_out_gp1  = axi_id_gp1_out[4:0];
              6:  id_out_gp1  = axi_id_gp1_out;    
              default : id_out_gp1 =  axi_id_gp1_out;              
        endcase
    end
    endfunction
    
    assign PU_UPS1_BID     = id_out_gp1(PU_UPS1_BID_out);
    assign PU_UPS1_RID     = id_out_gp1(PU_UPS1_RID_out);    
    
    // S_AXI_HP0    
    
    function [3:0] id_in_hp0;
       input [(P_AXI_HP0_ID_WIDTH - 1) : 0] axi_id_hp0_in;
    begin
        case (P_AXI_HP0_ID_WIDTH)
              1:  id_in_hp0  = {3'b0, axi_id_hp0_in};
              2:  id_in_hp0  = {2'b0, axi_id_hp0_in};
              3:  id_in_hp0  = {1'b0, axi_id_hp0_in};
              4:  id_in_hp0  = axi_id_hp0_in;    
              default : id_in_hp0 =  axi_id_hp0_in;
        endcase
    end
    endfunction

    assign PU_SPS0_ARID_in = id_in_hp0(PU_SPS0_ARID);
    assign PU_SPS0_AWID_in = id_in_hp0(PU_SPS0_AWID);

    function [3:0] id_out_hp0;
       input [(P_AXI_HP0_ID_WIDTH - 1) : 0] axi_id_hp0_out;
    begin
        case (P_AXI_HP0_ID_WIDTH)
              1:  id_out_hp0  = axi_id_hp0_out[0];
              2:  id_out_hp0  = axi_id_hp0_out[1:0];
              3:  id_out_hp0  = axi_id_hp0_out[2:0];
              4:  id_out_hp0  = axi_id_hp0_out;
              default : id_out_hp0 =  axi_id_hp0_out;              
        endcase
    end
    endfunction

    assign PU_SPS0_BID     = id_out_hp0(PU_SPS0_BID_out);
    assign PU_SPS0_RID     = id_out_hp0(PU_SPS0_RID_out);  
	
	wire [127:0] pu_sps0_rdata;
	assign PU_SPS0_RDATA = pu_sps0_rdata[P_AXI_HP0_DATA_WIDTH-1:0];
	wire [127:0] pu_sps0_wdata;
	assign pu_sps0_wdata = (P_AXI_HP0_DATA_WIDTH == 128) ? PU_SPS0_WDATA : {{(128-P_AXI_HP0_DATA_WIDTH){0}},PU_SPS0_WDATA};
	wire [15:0] pu_sps0_wstrb;
	assign pu_sps0_wstrb = (P_AXI_HP0_DATA_WIDTH == 128) ? PU_SPS0_WSTRB : {{(16-P_AXI_HP0_DATA_WIDTH/8){0}},PU_SPS0_WSTRB};
		
    // S_AXI_HP1    

    function [3:0] id_in_hp1;
       input [(P_AXI_HP1_ID_WIDTH - 1) : 0] axi_id_hp1_in;
    begin
        case (P_AXI_HP1_ID_WIDTH)
              1:  id_in_hp1  = {3'b0, axi_id_hp1_in};
              2:  id_in_hp1  = {2'b0, axi_id_hp1_in};
              3:  id_in_hp1  = {1'b0, axi_id_hp1_in};
              4:  id_in_hp1  = axi_id_hp1_in;    
              default : id_in_hp1 =  axi_id_hp1_in;
        endcase
    end
    endfunction

    assign PU_SPS1_ARID_in = id_in_hp1(PU_SPS1_ARID);
    assign PU_SPS1_AWID_in = id_in_hp1(PU_SPS1_AWID);

    function [3:0] id_out_hp1;
       input [(P_AXI_HP1_ID_WIDTH - 1) : 0] axi_id_hp1_out;
    begin
        case (P_AXI_HP1_ID_WIDTH)
              1:  id_out_hp1  = axi_id_hp1_out[0];
              2:  id_out_hp1  = axi_id_hp1_out[1:0];
              3:  id_out_hp1  = axi_id_hp1_out[2:0];
              4:  id_out_hp1  = axi_id_hp1_out;
              default : id_out_hp1 =  axi_id_hp1_out;              
        endcase
    end
    endfunction
    
    assign PU_SPS1_BID     = id_out_hp1(PU_SPS1_BID_out);
    assign PU_SPS1_RID     = id_out_hp1(PU_SPS1_RID_out); 
	
	wire [127:0] pu_sps1_rdata;
	assign PU_SPS1_RDATA = pu_sps1_rdata[P_AXI_HP1_DATA_WIDTH-1:0];
	wire [127:0] pu_sps1_wdata;
	assign pu_sps1_wdata = (P_AXI_HP1_DATA_WIDTH == 128) ? PU_SPS1_WDATA : {{(128-P_AXI_HP1_DATA_WIDTH){0}},PU_SPS1_WDATA};
	wire [15:0] pu_sps1_wstrb;
	assign pu_sps1_wstrb = (P_AXI_HP1_DATA_WIDTH == 128) ? PU_SPS1_WSTRB : {{(16-P_AXI_HP1_DATA_WIDTH/8){0}},PU_SPS1_WSTRB};
    
    
    // S_AXI_HP2    

    function [3:0] id_in_hp2;
       input [(P_AXI_HP2_ID_WIDTH - 1) : 0] axi_id_hp2_in;
    begin
        case (P_AXI_HP2_ID_WIDTH)
              1:  id_in_hp2  = {3'b0, axi_id_hp2_in};
              2:  id_in_hp2  = {2'b0, axi_id_hp2_in};
              3:  id_in_hp2  = {1'b0, axi_id_hp2_in};
              4:  id_in_hp2  = axi_id_hp2_in;    
              default : id_in_hp2 =  axi_id_hp2_in;
        endcase
    end
    endfunction
     
    assign PU_SPS2_ARID_in = id_in_hp2(PU_SPS2_ARID);
    assign PU_SPS2_AWID_in = id_in_hp2(PU_SPS2_AWID);
 

    function [3:0] id_out_hp2;
       input [(P_AXI_HP2_ID_WIDTH - 1) : 0] axi_id_hp2_out;
    begin
        case (P_AXI_HP2_ID_WIDTH)
              1:  id_out_hp2  = axi_id_hp2_out[0];
              2:  id_out_hp2  = axi_id_hp2_out[1:0];
              3:  id_out_hp2  = axi_id_hp2_out[2:0];
              4:  id_out_hp2  = axi_id_hp2_out;
              default : id_out_hp2 =  axi_id_hp2_out;              
        endcase
    end
    endfunction
    
    assign PU_SPS2_BID     = id_out_hp2(PU_SPS2_BID_out);
    assign PU_SPS2_RID     = id_out_hp2(PU_SPS2_RID_out);
    
	wire [63:0] pu_sps2_rdata;
	assign PU_SPS2_RDATA = pu_sps2_rdata[P_AXI_HP2_DATA_WIDTH-1:0];
	wire [63:0] pu_sps2_wdata;
	assign pu_sps2_wdata = (P_AXI_HP2_DATA_WIDTH == 64) ? PU_SPS2_WDATA : {{(64-P_AXI_HP2_DATA_WIDTH){0}},PU_SPS2_WDATA};
	wire [7:0] pu_sps2_wstrb;
	assign pu_sps2_wstrb = (P_AXI_HP2_DATA_WIDTH == 64) ? PU_SPS2_WSTRB : {{(8-P_AXI_HP2_DATA_WIDTH/8){0}},PU_SPS2_WSTRB};
    
    // S_AXI_HP3    

    function [3:0] id_in_hp3;
       input [(P_AXI_HP3_ID_WIDTH - 1) : 0] axi_id_hp3_in;
    begin
        case (P_AXI_HP3_ID_WIDTH)
              1:  id_in_hp3  = {3'b0, axi_id_hp3_in};
              2:  id_in_hp3  = {2'b0, axi_id_hp3_in};
              3:  id_in_hp3  = {1'b0, axi_id_hp3_in};
              4:  id_in_hp3  = axi_id_hp3_in;    
              default : id_in_hp3 =  axi_id_hp3_in;
        endcase
    end
    endfunction
     
    assign PU_SPS3_ARID_in = id_in_hp3(PU_SPS3_ARID);
    assign PU_SPS3_AWID_in = id_in_hp3(PU_SPS3_AWID);


    function [3:0] id_out_hp3;
       input [(P_AXI_HP3_ID_WIDTH - 1) : 0] axi_id_hp3_out;
    begin
        case (P_AXI_HP3_ID_WIDTH)
              1:  id_out_hp3  = axi_id_hp3_out[0];
              2:  id_out_hp3  = axi_id_hp3_out[1:0];
              3:  id_out_hp3  = axi_id_hp3_out[2:0];
              4:  id_out_hp3  = axi_id_hp3_out;
              default : id_out_hp3 =  axi_id_hp3_out;              
        endcase
    end
    endfunction
    
    assign PU_SPS3_BID     = id_out_hp3(PU_SPS3_BID_out);
    assign PU_SPS3_RID     = id_out_hp3(PU_SPS3_RID_out); 
    
    wire [63:0] pu_sps3_rdata;
	assign PU_SPS3_RDATA = pu_sps3_rdata[P_AXI_HP3_DATA_WIDTH-1:0];
	wire [63:0] pu_sps3_wdata;
	assign pu_sps3_wdata = (P_AXI_HP3_DATA_WIDTH == 64) ? PU_SPS3_WDATA : {{(64-P_AXI_HP3_DATA_WIDTH){0}},PU_SPS3_WDATA};
	wire [7:0] pu_sps3_wstrb;
	assign pu_sps3_wstrb = (P_AXI_HP3_DATA_WIDTH == 64) ? PU_SPS3_WSTRB : {{(8-P_AXI_HP3_DATA_WIDTH/8){0}},PU_SPS3_WSTRB};
	
	
    // S_AXI_ACP    

    function [4:0] id_in_acp;
       input [(P_AXI_ACP_ID_WIDTH - 1) : 0] axi_id_acp_in;
     begin
        case (P_AXI_ACP_ID_WIDTH)
              1:  id_in_acp  = {4'b0, axi_id_acp_in};
              2:  id_in_acp  = {3'b0, axi_id_acp_in};
              3:  id_in_acp  = {2'b0,axi_id_acp_in};
              4:  id_in_acp  = {1'b0,axi_id_acp_in};
              5:  id_in_acp  = axi_id_acp_in;
              default : id_in_acp =  axi_id_acp_in;
        endcase
     end
     endfunction

    assign PU_ACPS_ARID_in = id_in_acp(S_AXI_ACP_ARID_W);
    assign PU_ACPS_AWID_in = id_in_acp(S_AXI_ACP_AWID_W);
    assign PU_ACPS_WID_in  = id_in_acp(S_AXI_ACP_WID_W);

     function [4:0] id_out_acp;
       input [(P_AXI_ACP_ID_WIDTH - 1) : 0] axi_id_acp_out;
     begin
        case (P_AXI_ACP_ID_WIDTH)
              1:  id_out_acp  = axi_id_acp_out[0];
              2:  id_out_acp  = axi_id_acp_out[1:0];
              3:  id_out_acp  = axi_id_acp_out[2:0];
              4:  id_out_acp  = axi_id_acp_out[3:0];
              5:  id_out_acp  = axi_id_acp_out;
              default : id_out_acp =  axi_id_acp_out;              
        endcase
     end
     endfunction
    
    assign S_AXI_ACP_BID_W     = id_out_acp(PU_ACPS_BID_out);
    assign S_AXI_ACP_RID_W     = id_out_acp(PU_ACPS_RID_out);  

// Generating the AxUSER Values locally when the C_USE_DEFAULT_ACP_USER_VAL is enabled.
// Otherwise a master connected to the ACP port will drive the AxUSER Ports 
wire S_AXI_ACP_AWREADY_W;
wire S_AXI_ACP_WREADY_W;
wire S_AXI_ACP_BVALID_W;    
wire S_AXI_ACP_RLAST_W;  
wire S_AXI_ACP_RVALID_W; 
wire S_AXI_ACP_ARREADY_W;
wire [1:0] S_AXI_ACP_BRESP_W;
wire [1:0] S_AXI_ACP_RRESP_W;
wire [P_AXI_ACP_DATA_WIDTH-1:0] S_AXI_ACP_RDATA_W;  

wire S_AXI_ATC_ARVALID;
wire S_AXI_ATC_AWVALID;
wire S_AXI_ATC_BREADY;
wire S_AXI_ATC_RREADY;
wire S_AXI_ATC_WLAST;
wire S_AXI_ATC_WVALID;
wire [(P_AXI_ACP_ID_WIDTH-1) : 0] S_AXI_ATC_ARID;
wire [2:0] S_AXI_ATC_ARPROT;
wire [(P_AXI_ACP_ID_WIDTH-1) : 0] S_AXI_ATC_AWID;
wire [2:0] S_AXI_ATC_AWPROT;
wire [(P_AXI_ACP_ID_WIDTH-1) : 0] S_AXI_ATC_WID;
wire [31:0] S_AXI_ATC_ARADDR;
wire [31:0] S_AXI_ATC_AWADDR;
wire [3:0] S_AXI_ATC_ARCACHE;
wire [3:0] S_AXI_ATC_ARLEN;
wire [3:0] S_AXI_ATC_ARQOS;
wire [3:0] S_AXI_ATC_AWCACHE;
wire [3:0] S_AXI_ATC_AWLEN;
wire [3:0] S_AXI_ATC_AWQOS;  

wire [4:0] S_AXI_ATC_ARUSER;
wire [4:0] S_AXI_ATC_AWUSER; 

wire S_AXI_ACP_ARVALID_W;
wire S_AXI_ACP_AWVALID_W;
wire S_AXI_ACP_BREADY_W;
wire S_AXI_ACP_RREADY_W;
wire S_AXI_ACP_WLAST_W;
wire S_AXI_ACP_WVALID_W;
wire [2:0] S_AXI_ACP_ARPROT_W;
wire [2:0] S_AXI_ACP_AWPROT_W;
wire [31:0] S_AXI_ACP_ARADDR_W;
wire [31:0] S_AXI_ACP_AWADDR_W;
wire [3:0] S_AXI_ACP_ARCACHE_W;
wire [3:0] S_AXI_ACP_ARLEN_W;

wire [3:0] S_AXI_ACP_AWCACHE_W;
wire [3:0] S_AXI_ACP_AWLEN_W;

wire [4:0] S_AXI_ACP_ARUSER_W;
wire [4:0] S_AXI_ACP_AWUSER_W;

wire [P_AXI_ACP_DATA_WIDTH-1:0] S_AXI_ATC_WDATA;
wire [P_AXI_ACP_DATA_WIDTH/8-1:0] S_AXI_ATC_WSTRB; 

wire [P_AXI_ACP_DATA_WIDTH-1:0] S_AXI_ACP_WDATA_W;
wire [P_AXI_ACP_DATA_WIDTH/8-1:0] S_AXI_ACP_WSTRB_W;

// AxUSER signal update
wire [4:0] param_aruser;
wire [4:0] param_awuser;

assign param_aruser = P_USE_DEFAULT_ACP_USER_VAL ? P_AXI_ACP_ARUSER_VAL : 5'b0;
assign param_awuser = P_USE_DEFAULT_ACP_USER_VAL ? P_AXI_ACP_AWUSER_VAL : 5'b0;

assign  S_AXI_ACP_ARADDR_W      = (P_INCLUDE_ACP_TRANS_CHECK == 1) ? S_AXI_ATC_ARADDR  : PU_ACPS_ARADDR;
assign  S_AXI_ACP_ARCACHE_W     = (P_INCLUDE_ACP_TRANS_CHECK == 1) ? S_AXI_ATC_ARCACHE : PU_ACPS_ARCACHE;
assign  S_AXI_ACP_ARLEN_W       = (P_INCLUDE_ACP_TRANS_CHECK == 1) ? S_AXI_ATC_ARLEN   : PU_ACPS_ARLEN;
assign  S_AXI_ACP_ARPROT_W      = (P_INCLUDE_ACP_TRANS_CHECK == 1) ? S_AXI_ATC_ARPROT  : PU_ACPS_ARPROT;
assign  S_AXI_ACP_ARUSER_W      = (P_INCLUDE_ACP_TRANS_CHECK == 1) ? S_AXI_ATC_ARUSER  : param_aruser;
assign  S_AXI_ACP_ARVALID_W     = (P_INCLUDE_ACP_TRANS_CHECK == 1) ? S_AXI_ATC_ARVALID : PU_ACPS_ARVALID;

assign  S_AXI_ACP_AWADDR_W      = (P_INCLUDE_ACP_TRANS_CHECK == 1) ? S_AXI_ATC_AWADDR  : PU_ACPS_AWADDR;
assign  S_AXI_ACP_AWCACHE_W     = (P_INCLUDE_ACP_TRANS_CHECK == 1) ? S_AXI_ATC_AWCACHE : PU_ACPS_AWCACHE;
assign  S_AXI_ACP_AWLEN_W       = (P_INCLUDE_ACP_TRANS_CHECK == 1) ? S_AXI_ATC_AWLEN   : PU_ACPS_AWLEN;
assign  S_AXI_ACP_AWPROT_W      = (P_INCLUDE_ACP_TRANS_CHECK == 1) ? S_AXI_ATC_AWPROT  : PU_ACPS_AWPROT;
assign  S_AXI_ACP_AWUSER_W      = (P_INCLUDE_ACP_TRANS_CHECK == 1) ? S_AXI_ATC_AWUSER  : param_awuser;
assign  S_AXI_ACP_AWVALID_W     = (P_INCLUDE_ACP_TRANS_CHECK == 1) ? S_AXI_ATC_AWVALID : PU_ACPS_AWVALID;

assign  S_AXI_ACP_BREADY_W      = (P_INCLUDE_ACP_TRANS_CHECK == 1) ? S_AXI_ATC_BREADY  : PU_ACPS_BREADY;
assign  S_AXI_ACP_RREADY_W      = (P_INCLUDE_ACP_TRANS_CHECK == 1) ? S_AXI_ATC_RREADY  : PU_ACPS_RREADY;
assign  S_AXI_ACP_WDATA_W       = (P_INCLUDE_ACP_TRANS_CHECK == 1) ? S_AXI_ATC_WDATA   : PU_ACPS_WDATA;
assign  S_AXI_ACP_WLAST_W       = (P_INCLUDE_ACP_TRANS_CHECK == 1) ? S_AXI_ATC_WLAST   : PU_ACPS_WLAST;
assign  S_AXI_ACP_WSTRB_W       = (P_INCLUDE_ACP_TRANS_CHECK == 1) ? S_AXI_ATC_WSTRB   : PU_ACPS_WSTRB;  
assign  S_AXI_ACP_WVALID_W      = (P_INCLUDE_ACP_TRANS_CHECK == 1) ? S_AXI_ATC_WVALID  : PU_ACPS_WVALID;      

assign  S_AXI_ACP_ARID_W        = (P_INCLUDE_ACP_TRANS_CHECK == 1) ? S_AXI_ATC_ARID    : PU_ACPS_ARID;    
assign  S_AXI_ACP_AWID_W        = (P_INCLUDE_ACP_TRANS_CHECK == 1) ? S_AXI_ATC_AWID    : PU_ACPS_AWID;      
assign  S_AXI_ACP_WID_W         = (P_INCLUDE_ACP_TRANS_CHECK == 1) ? S_AXI_ATC_WID     : PU_ACPS_WID;        
  

  generate
    if (P_INCLUDE_ACP_TRANS_CHECK == 0) begin : gen_no_atc
    
    assign PU_ACPS_AWREADY          =   S_AXI_ACP_AWREADY_W;
    assign PU_ACPS_WREADY           =   S_AXI_ACP_WREADY_W;
    assign PU_ACPS_BID              =   S_AXI_ACP_BID_W;    
    assign PU_ACPS_BRESP            =   S_AXI_ACP_BRESP_W;  
    assign PU_ACPS_BVALID           =   S_AXI_ACP_BVALID_W;    
    assign PU_ACPS_RDATA            =   S_AXI_ACP_RDATA_W;    
    assign PU_ACPS_RID              =   S_AXI_ACP_RID_W;        
    assign PU_ACPS_RLAST            =   S_AXI_ACP_RLAST_W;  
    assign PU_ACPS_RRESP            =   S_AXI_ACP_RRESP_W;  
    assign PU_ACPS_RVALID           =   S_AXI_ACP_RVALID_W; 
    assign PU_ACPS_ARREADY          =   S_AXI_ACP_ARREADY_W;
    
    end else begin : gen_atc
    
  pu_atm #(
   .C_AXI_ID_WIDTH                   (P_AXI_ACP_ID_WIDTH),
   .C_AXI_DATA_WIDTH                 (P_AXI_ACP_DATA_WIDTH),
   .C_AXI_AWUSER_WIDTH               (5),
   .C_AXI_ARUSER_WIDTH               (5)
   )
  atc_i (
   // Global Signals
   .ACLK                                 (S_AXI_ACP_ACLK_temp),
   .ARESETN                              (PU_ACPS_ARESETN),
   // Slave Interface Write Address Ports
   .S_AXI_AWID                           (PU_ACPS_AWID),
   .S_AXI_AWADDR                         (PU_ACPS_AWADDR),
   .S_AXI_AWLEN                          (PU_ACPS_AWLEN),
   .S_AXI_AWCACHE                        (PU_ACPS_AWCACHE),
   .S_AXI_AWPROT                         (PU_ACPS_AWPROT),
   .S_AXI_AWUSER                         (param_awuser),
   .S_AXI_AWVALID                        (PU_ACPS_AWVALID),
   .S_AXI_AWREADY                        (PU_ACPS_AWREADY),
   // Slave Interface Write Data Ports
   .S_AXI_WID                            (PU_ACPS_WID),
   .S_AXI_WDATA                          (PU_ACPS_WDATA),
   .S_AXI_WSTRB                          (PU_ACPS_WSTRB),
   .S_AXI_WLAST                          (PU_ACPS_WLAST),
   .S_AXI_WUSER                          (1'b0),
   .S_AXI_WVALID                         (PU_ACPS_WVALID),
   .S_AXI_WREADY                         (PU_ACPS_WREADY),
   // Slave Interface Write Response Ports
   .S_AXI_BID                            (PU_ACPS_BID),
   .S_AXI_BRESP                          (PU_ACPS_BRESP),
   .S_AXI_BUSER                          (),
   .S_AXI_BVALID                         (PU_ACPS_BVALID),
   .S_AXI_BREADY                         (PU_ACPS_BREADY),
   // Slave Interface Read Address Ports
   .S_AXI_ARID                           (PU_ACPS_ARID),
   .S_AXI_ARADDR                         (PU_ACPS_ARADDR),
   .S_AXI_ARLEN                          (PU_ACPS_ARLEN),
   .S_AXI_ARCACHE                        (PU_ACPS_ARCACHE),
   .S_AXI_ARPROT                         (PU_ACPS_ARPROT),
   .S_AXI_ARUSER                         (param_aruser),
   .S_AXI_ARVALID                        (PU_ACPS_ARVALID),
   .S_AXI_ARREADY                        (PU_ACPS_ARREADY),
   // Slave Interface Read Data Ports
   .S_AXI_RID                            (PU_ACPS_RID),
   .S_AXI_RDATA                          (PU_ACPS_RDATA),
   .S_AXI_RRESP                          (PU_ACPS_RRESP),
   .S_AXI_RLAST                          (PU_ACPS_RLAST),
   .S_AXI_RUSER                          (),
   .S_AXI_RVALID                         (PU_ACPS_RVALID),
   .S_AXI_RREADY                         (PU_ACPS_RREADY),
    // Slave Interface Write Address Ports
   .M_AXI_AWID                           (S_AXI_ATC_AWID),
   .M_AXI_AWADDR                         (S_AXI_ATC_AWADDR),
   .M_AXI_AWLEN                          (S_AXI_ATC_AWLEN),
   .M_AXI_AWCACHE                        (S_AXI_ATC_AWCACHE),
   .M_AXI_AWPROT                         (S_AXI_ATC_AWPROT),
   .M_AXI_AWUSER                         (S_AXI_ATC_AWUSER),
   .M_AXI_AWVALID                        (S_AXI_ATC_AWVALID),
   .M_AXI_AWREADY                        (S_AXI_ACP_AWREADY_W),
   // Slave Interface Write Data Ports
   .M_AXI_WID                            (S_AXI_ATC_WID),
   .M_AXI_WDATA                          (S_AXI_ATC_WDATA),
   .M_AXI_WSTRB                          (S_AXI_ATC_WSTRB),
   .M_AXI_WLAST                          (S_AXI_ATC_WLAST),
   .M_AXI_WUSER                          (),
   .M_AXI_WVALID                         (S_AXI_ATC_WVALID),
   .M_AXI_WREADY                         (S_AXI_ACP_WREADY_W),
   // Slave Interface Write Response Ports
   .M_AXI_BID                            (S_AXI_ACP_BID_W),
   .M_AXI_BRESP                          (S_AXI_ACP_BRESP_W),
   .M_AXI_BUSER                          (1'b0),
   .M_AXI_BVALID                         (S_AXI_ACP_BVALID_W),
   .M_AXI_BREADY                         (S_AXI_ATC_BREADY),
   // Slave Interface Read Address Ports
   .M_AXI_ARID                           (S_AXI_ATC_ARID),
   .M_AXI_ARADDR                         (S_AXI_ATC_ARADDR),
   .M_AXI_ARLEN                          (S_AXI_ATC_ARLEN),
   .M_AXI_ARCACHE                        (S_AXI_ATC_ARCACHE),
   .M_AXI_ARPROT                         (S_AXI_ATC_ARPROT),
   .M_AXI_ARUSER                         (S_AXI_ATC_ARUSER),
   .M_AXI_ARVALID                        (S_AXI_ATC_ARVALID),
   .M_AXI_ARREADY                        (S_AXI_ACP_ARREADY_W),
   // Slave Interface Read Data Ports
   .M_AXI_RID                            (S_AXI_ACP_RID_W),
   .M_AXI_RDATA                          (S_AXI_ACP_RDATA_W),
   .M_AXI_RRESP                          (S_AXI_ACP_RRESP_W),
   .M_AXI_RLAST                          (S_AXI_ACP_RLAST_W),
   .M_AXI_RUSER                          (1'b0),
   .M_AXI_RVALID                         (S_AXI_ACP_RVALID_W),
   .M_AXI_RREADY                         (S_AXI_ATC_RREADY),
   
   .S_AXI_AWSIZE(1'b0),
   .S_AXI_AWBURST(1'b0),
   .S_AXI_AWLOCK(1'b0),

   .S_AXI_ARSIZE(1'b0),
   .S_AXI_ARBURST(1'b0),
   .S_AXI_ARLOCK(1'b0),
   
   .ERROR_INDICATION(),
   .ERROR_TRANSACTION_ID()
   );    

    end
  endgenerate

GTP_SOC system_process_unit_soc_inst
(
    .PU_ACPS_ACLK(S_AXI_ACP_ACLK_temp),
    .PU_ACPS_ARESETN(PU_ACPS_ARESETN),
    .PU_ACPS_AWVALID(S_AXI_ACP_AWVALID_W),
    .PU_ACPS_AWADDR(S_AXI_ACP_AWADDR_W),
    .PU_ACPS_AWID(PU_ACPS_AWID_in),
    .PU_ACPS_AWLEN(S_AXI_ACP_AWLEN_W),
    .PU_ACPS_AWCACHE(S_AXI_ACP_AWCACHE_W),
    .PU_ACPS_AWPROT(S_AXI_ACP_AWPROT_W),
    .PU_ACPS_AWREADY(S_AXI_ACP_AWREADY_W),
    .PU_ACPS_WVALID(S_AXI_ACP_WVALID_W),
    .PU_ACPS_WID(PU_ACPS_WID_in),
    .PU_ACPS_WDATA(S_AXI_ACP_WDATA_W),
    .PU_ACPS_WSTRB(S_AXI_ACP_WSTRB_W),
    .PU_ACPS_WLAST(S_AXI_ACP_WLAST_W),
    .PU_ACPS_WREADY(S_AXI_ACP_WREADY_W),
    .PU_ACPS_BVALID(S_AXI_ACP_BVALID_W),
    .PU_ACPS_BID(PU_ACPS_BID_out),
    .PU_ACPS_BRESP(S_AXI_ACP_BRESP_W),
    .PU_ACPS_BREADY(S_AXI_ACP_BREADY_W),
    .PU_ACPS_ARVALID(S_AXI_ACP_ARVALID_W),
    .PU_ACPS_ARID(PU_ACPS_ARID_in),
    .PU_ACPS_ARADDR(S_AXI_ACP_ARADDR_W),
    .PU_ACPS_ARLEN(S_AXI_ACP_ARLEN_W),
    .PU_ACPS_ARCACHE(S_AXI_ACP_ARCACHE_W),
    .PU_ACPS_ARPROT(S_AXI_ACP_ARPROT_W),
    .PU_ACPS_ARREADY(S_AXI_ACP_ARREADY_W),
    .PU_ACPS_RVALID(S_AXI_ACP_RVALID_W),
    .PU_ACPS_RID(PU_ACPS_RID_out),
    .PU_ACPS_RDATA(S_AXI_ACP_RDATA_W),
    .PU_ACPS_RRESP(S_AXI_ACP_RRESP_W),
    .PU_ACPS_RLAST(S_AXI_ACP_RLAST_W),
    .PU_ACPS_RREADY(S_AXI_ACP_RREADY_W),
	
    .PU_UPM0_CLK(M_AXI_UPM0_ACLK_temp),
    .PU_UPM0_RESETN(PU_UPM0_RESETN),
    .PU_UPM0_ARADDR(PU_UPM0_ARADDR),
    .PU_UPM0_ARBURST(PU_UPM0_ARBURST),
    .PU_UPM0_ARCACHE(PU_UPM0_ARCACHE),
    .PU_UPM0_ARID(PU_UPM0_ARID_FULL),
    .PU_UPM0_ARLEN(PU_UPM0_ARLEN),
    .PU_UPM0_ARLOCK(PU_UPM0_ARLOCK),
    .PU_UPM0_ARPROT(PU_UPM0_ARPROT),
    .PU_UPM0_ARREADY(PU_UPM0_ARREADY),
    .PU_UPM0_ARSIZE(PU_UPM0_ARSIZE),
    .PU_UPM0_ARVALID(PU_UPM0_ARVALID),
    .PU_UPM0_AWADDR(PU_UPM0_AWADDR),
    .PU_UPM0_AWBURST(PU_UPM0_AWBURST),
    .PU_UPM0_AWCACHE(PU_UPM0_AWCACHE),
    .PU_UPM0_AWID(PU_UPM0_AWID_FULL),
    .PU_UPM0_AWLEN(PU_UPM0_AWLEN),
    .PU_UPM0_AWLOCK(PU_UPM0_AWLOCK),
    .PU_UPM0_AWPROT(PU_UPM0_AWPROT),
    .PU_UPM0_AWREADY(PU_UPM0_AWREADY),
    .PU_UPM0_AWSIZE(PU_UPM0_AWSIZE),
    .PU_UPM0_AWVALID(PU_UPM0_AWVALID),
    .PU_UPM0_BID(PU_UPM0_BID_FULL),
    .PU_UPM0_BREADY(PU_UPM0_BREADY),
    .PU_UPM0_BRESP(PU_UPM0_BRESP),
    .PU_UPM0_BVALID(PU_UPM0_BVALID),
    .PU_UPM0_RDATA(PU_UPM0_RDATA),
    .PU_UPM0_RID(PU_UPM0_RID_FULL),
    .PU_UPM0_RLAST(PU_UPM0_RLAST),
    .PU_UPM0_RREADY(PU_UPM0_RREADY),
    .PU_UPM0_RRESP(PU_UPM0_RRESP),
    .PU_UPM0_RVALID(PU_UPM0_RVALID),
    .PU_UPM0_WDATA(PU_UPM0_WDATA),
    .PU_UPM0_WLAST(PU_UPM0_WLAST),
    .PU_UPM0_WREADY(PU_UPM0_WREADY),
    .PU_UPM0_WSTRB(PU_UPM0_WSTRB),
    .PU_UPM0_WVALID(PU_UPM0_WVALID),

    .PU_UPM1_CLK(M_AXI_UPM1_ACLK_temp),
    .PU_UPM1_RESETN(PU_UPM1_RESETN),
    .PU_UPM1_ARADDR(PU_UPM1_ARADDR),
    .PU_UPM1_ARBURST(PU_UPM1_ARBURST),
    .PU_UPM1_ARCACHE(PU_UPM1_ARCACHE),
    .PU_UPM1_ARID(PU_UPM1_ARID_FULL),
    .PU_UPM1_ARLEN(PU_UPM1_ARLEN),
    .PU_UPM1_ARLOCK(PU_UPM1_ARLOCK),
    .PU_UPM1_ARPROT(PU_UPM1_ARPROT),
    .PU_UPM1_ARREADY(PU_UPM1_ARREADY),
    .PU_UPM1_ARSIZE(PU_UPM1_ARSIZE),
    .PU_UPM1_ARVALID(PU_UPM1_ARVALID),
    .PU_UPM1_AWADDR(PU_UPM1_AWADDR),
    .PU_UPM1_AWBURST(PU_UPM1_AWBURST),
    .PU_UPM1_AWCACHE(PU_UPM1_AWCACHE),
    .PU_UPM1_AWID(PU_UPM1_AWID_FULL),
    .PU_UPM1_AWLEN(PU_UPM1_AWLEN),
    .PU_UPM1_AWLOCK(PU_UPM1_AWLOCK),
    .PU_UPM1_AWPROT(PU_UPM1_AWPROT),
    .PU_UPM1_AWREADY(PU_UPM1_AWREADY),
    .PU_UPM1_AWSIZE(PU_UPM1_AWSIZE),
    .PU_UPM1_AWVALID(PU_UPM1_AWVALID),
    .PU_UPM1_BID(PU_UPM1_BID_FULL),
    .PU_UPM1_BREADY(PU_UPM1_BREADY),
    .PU_UPM1_BRESP(PU_UPM1_BRESP),
    .PU_UPM1_BVALID(PU_UPM1_BVALID),
    .PU_UPM1_RDATA(PU_UPM1_RDATA),
    .PU_UPM1_RID(PU_UPM1_RID_FULL),
    .PU_UPM1_RLAST(PU_UPM1_RLAST),
    .PU_UPM1_RREADY(PU_UPM1_RREADY),
    .PU_UPM1_RRESP(PU_UPM1_RRESP),
    .PU_UPM1_RVALID(PU_UPM1_RVALID),
    .PU_UPM1_WDATA(PU_UPM1_WDATA),
    .PU_UPM1_WLAST(PU_UPM1_WLAST),
    .PU_UPM1_WREADY(PU_UPM1_WREADY),
    .PU_UPM1_WSTRB(PU_UPM1_WSTRB),
    .PU_UPM1_WVALID(PU_UPM1_WVALID),

    .PU_UPS0_CLK(S_AXI_UPS0_ACLK_temp),
    .PU_UPS0_RESETN(PU_UPS0_RESETN),
    .PU_UPS0_ARADDR(PU_UPS0_ARADDR),
    .PU_UPS0_ARBURST(PU_UPS0_ARBURST),
    .PU_UPS0_ARCACHE(PU_UPS0_ARCACHE),
    .PU_UPS0_ARID(PU_UPS0_ARID_in),
    .PU_UPS0_ARLEN(PU_UPS0_ARLEN),
    .PU_UPS0_ARLOCK(PU_UPS0_ARLOCK),
    .PU_UPS0_ARPROT(PU_UPS0_ARPROT),
    .PU_UPS0_ARREADY(PU_UPS0_ARREADY),
    .PU_UPS0_ARSIZE(PU_UPS0_ARSIZE),
    .PU_UPS0_ARVALID(PU_UPS0_ARVALID),
    .PU_UPS0_AWADDR(PU_UPS0_AWADDR),
    .PU_UPS0_AWBURST(PU_UPS0_AWBURST),
    .PU_UPS0_AWCACHE(PU_UPS0_AWCACHE),
    .PU_UPS0_AWID(PU_UPS0_AWID_in),
    .PU_UPS0_AWLEN(PU_UPS0_AWLEN),
    .PU_UPS0_AWLOCK(PU_UPS0_AWLOCK),
    .PU_UPS0_AWPROT(PU_UPS0_AWPROT),
    .PU_UPS0_AWREADY(PU_UPS0_AWREADY),
    .PU_UPS0_AWSIZE(PU_UPS0_AWSIZE),
    .PU_UPS0_AWVALID(PU_UPS0_AWVALID),
    .PU_UPS0_BID(PU_UPS0_BID_out),
    .PU_UPS0_BREADY(PU_UPS0_BREADY),
    .PU_UPS0_BRESP(PU_UPS0_BRESP),
    .PU_UPS0_BVALID(PU_UPS0_BVALID),
    .PU_UPS0_RDATA(PU_UPS0_RDATA),
    .PU_UPS0_RID(PU_UPS0_RID_out),
    .PU_UPS0_RLAST(PU_UPS0_RLAST),
    .PU_UPS0_RREADY(PU_UPS0_RREADY),
    .PU_UPS0_RRESP(PU_UPS0_RRESP),
    .PU_UPS0_RVALID(PU_UPS0_RVALID),
    .PU_UPS0_WDATA(PU_UPS0_WDATA),
    .PU_UPS0_WLAST(PU_UPS0_WLAST),
    .PU_UPS0_WREADY(PU_UPS0_WREADY),
    .PU_UPS0_WSTRB(PU_UPS0_WSTRB),
    .PU_UPS0_WVALID(PU_UPS0_WVALID),

    .PU_UPS1_CLK(S_AXI_UPS1_ACLK_temp),
    .PU_UPS1_RESETN(PU_UPS1_RESETN),
    .PU_UPS1_ARADDR(PU_UPS1_ARADDR),
    .PU_UPS1_ARBURST(PU_UPS1_ARBURST),
    .PU_UPS1_ARCACHE(PU_UPS1_ARCACHE),
    .PU_UPS1_ARID(PU_UPS1_ARID_in),
    .PU_UPS1_ARLEN(PU_UPS1_ARLEN),
    .PU_UPS1_ARLOCK(PU_UPS1_ARLOCK),
    .PU_UPS1_ARPROT(PU_UPS1_ARPROT),
    .PU_UPS1_ARREADY(PU_UPS1_ARREADY),
    .PU_UPS1_ARSIZE(PU_UPS1_ARSIZE),
    .PU_UPS1_ARVALID(PU_UPS1_ARVALID),
    .PU_UPS1_AWADDR(PU_UPS1_AWADDR),
    .PU_UPS1_AWBURST(PU_UPS1_AWBURST),
    .PU_UPS1_AWCACHE(PU_UPS1_AWCACHE),
    .PU_UPS1_AWID(PU_UPS1_AWID_in),
    .PU_UPS1_AWLEN(PU_UPS1_AWLEN),
    .PU_UPS1_AWLOCK(PU_UPS1_AWLOCK),
    .PU_UPS1_AWPROT(PU_UPS1_AWPROT),
    .PU_UPS1_AWREADY(PU_UPS1_AWREADY),
    .PU_UPS1_AWSIZE(PU_UPS1_AWSIZE),
    .PU_UPS1_AWVALID(PU_UPS1_AWVALID),
    .PU_UPS1_BID(PU_UPS1_BID_out),
    .PU_UPS1_BREADY(PU_UPS1_BREADY),
    .PU_UPS1_BRESP(PU_UPS1_BRESP),
    .PU_UPS1_BVALID(PU_UPS1_BVALID),
    .PU_UPS1_RDATA(PU_UPS1_RDATA),
    .PU_UPS1_RID(PU_UPS1_RID_out),
    .PU_UPS1_RLAST(PU_UPS1_RLAST),
    .PU_UPS1_RREADY(PU_UPS1_RREADY),
    .PU_UPS1_RRESP(PU_UPS1_RRESP),
    .PU_UPS1_RVALID(PU_UPS1_RVALID),
    .PU_UPS1_WDATA(PU_UPS1_WDATA),
    .PU_UPS1_WLAST(PU_UPS1_WLAST),
    .PU_UPS1_WREADY(PU_UPS1_WREADY),
    .PU_UPS1_WSTRB(PU_UPS1_WSTRB),
    .PU_UPS1_WVALID(PU_UPS1_WVALID),

    .PU_SPS0_CLK(S_AXI_SPS0_ACLK_temp),
    .PU_SPS0_RESETN(PU_SPS0_RESETN),
    .PU_SPS0_AWVALID(PU_SPS0_AWVALID),
    .PU_SPS0_AWADDR(PU_SPS0_AWADDR),
    .PU_SPS0_AWID(PU_SPS0_AWID_in),
    .PU_SPS0_AWLEN(PU_SPS0_AWLEN),
    .PU_SPS0_AWSIZE(PU_SPS0_AWSIZE),
    .PU_SPS0_AWBURST(PU_SPS0_AWBURST),
    .PU_SPS0_AWLOCK(PU_SPS0_AWLOCK),
    .PU_SPS0_AWCACHE(PU_SPS0_AWCACHE),
    .PU_SPS0_AWPROT(PU_SPS0_AWPROT),
    .PU_SPS0_AWQOS(PU_SPS0_AWQOS),
    .PU_SPS0_AWREADY(PU_SPS0_AWREADY),
    .PU_SPS0_WVALID(PU_SPS0_WVALID),
    .PU_SPS0_WDATA(pu_sps0_wdata),
    .PU_SPS0_WSTRB(pu_sps0_wstrb),
    .PU_SPS0_WLAST(PU_SPS0_WLAST),
    .PU_SPS0_WREADY(PU_SPS0_WREADY),
    .PU_SPS0_BVALID(PU_SPS0_BVALID),
    .PU_SPS0_BID(PU_SPS0_BID_out),
    .PU_SPS0_BRESP(PU_SPS0_BRESP),
    .PU_SPS0_BREADY(PU_SPS0_BREADY),
    .PU_SPS0_ARVALID(PU_SPS0_ARVALID),
    .PU_SPS0_ARID(PU_SPS0_ARID_in),
    .PU_SPS0_ARADDR(PU_SPS0_ARADDR),
    .PU_SPS0_ARLEN(PU_SPS0_ARLEN),
    .PU_SPS0_ARSIZE(PU_SPS0_ARSIZE),
    .PU_SPS0_ARBURST(PU_SPS0_ARBURST),
    .PU_SPS0_ARLOCK(PU_SPS0_ARLOCK),
    .PU_SPS0_ARCACHE(PU_SPS0_ARCACHE),
    .PU_SPS0_ARPROT(PU_SPS0_ARPROT),
    .PU_SPS0_ARQOS(PU_SPS0_ARQOS),
    .PU_SPS0_ARREADY(PU_SPS0_ARREADY),
    .PU_SPS0_RVALID(PU_SPS0_RVALID),
    .PU_SPS0_RID(PU_SPS0_RID_out),
    .PU_SPS0_RDATA(pu_sps0_rdata),
    .PU_SPS0_RRESP(PU_SPS0_RRESP),
    .PU_SPS0_RLAST(PU_SPS0_RLAST),
    .PU_SPS0_RREADY(PU_SPS0_RREADY),

    .PU_SPS1_CLK(S_AXI_SPS1_ACLK_temp),
    .PU_SPS1_RESETN(PU_SPS1_RESETN),
    .PU_SPS1_AWVALID(PU_SPS1_AWVALID),
    .PU_SPS1_AWADDR(PU_SPS1_AWADDR),
    .PU_SPS1_AWID(PU_SPS1_AWID_in),
    .PU_SPS1_AWLEN(PU_SPS1_AWLEN),
    .PU_SPS1_AWSIZE(PU_SPS1_AWSIZE),
    .PU_SPS1_AWBURST(PU_SPS1_AWBURST),
    .PU_SPS1_AWLOCK(PU_SPS1_AWLOCK),
    .PU_SPS1_AWCACHE(PU_SPS1_AWCACHE),
    .PU_SPS1_AWPROT(PU_SPS1_AWPROT),
    .PU_SPS1_AWQOS(PU_SPS1_AWQOS),
    .PU_SPS1_AWREADY(PU_SPS1_AWREADY),
    .PU_SPS1_WVALID(PU_SPS1_WVALID),
    .PU_SPS1_WDATA(pu_sps1_wdata),
    .PU_SPS1_WSTRB(pu_sps1_wstrb),
    .PU_SPS1_WLAST(PU_SPS1_WLAST),
    .PU_SPS1_WREADY(PU_SPS1_WREADY),
    .PU_SPS1_BVALID(PU_SPS1_BVALID),
    .PU_SPS1_BID(PU_SPS1_BID_out),
    .PU_SPS1_BRESP(PU_SPS1_BRESP),
    .PU_SPS1_BREADY(PU_SPS1_BREADY),
    .PU_SPS1_ARVALID(PU_SPS1_ARVALID),
    .PU_SPS1_ARID(PU_SPS1_ARID_in),
    .PU_SPS1_ARADDR(PU_SPS1_ARADDR),
    .PU_SPS1_ARLEN(PU_SPS1_ARLEN),
    .PU_SPS1_ARSIZE(PU_SPS1_ARSIZE),
    .PU_SPS1_ARBURST(PU_SPS1_ARBURST),
    .PU_SPS1_ARLOCK(PU_SPS1_ARLOCK),
    .PU_SPS1_ARCACHE(PU_SPS1_ARCACHE),
    .PU_SPS1_ARPROT(PU_SPS1_ARPROT),
    .PU_SPS1_ARQOS(PU_SPS1_ARQOS),
    .PU_SPS1_ARREADY(PU_SPS1_ARREADY),
    .PU_SPS1_RVALID(PU_SPS1_RVALID),
    .PU_SPS1_RID(PU_SPS1_RID_out),
    .PU_SPS1_RDATA(pu_sps1_rdata),
    .PU_SPS1_RRESP(PU_SPS1_RRESP),
    .PU_SPS1_RLAST(PU_SPS1_RLAST),
    .PU_SPS1_RREADY(PU_SPS1_RREADY),

    .PU_SPS2_CLK(S_AXI_SPS2_ACLK_temp),
    .PU_SPS2_RESETN(PU_SPS2_RESETN),
    .PU_SPS2_AWVALID(PU_SPS2_AWVALID),
    .PU_SPS2_AWADDR(PU_SPS2_AWADDR),
    .PU_SPS2_AWID(PU_SPS2_AWID_in),
    .PU_SPS2_AWLEN(PU_SPS2_AWLEN),
    .PU_SPS2_AWSIZE(PU_SPS2_AWSIZE),
    .PU_SPS2_AWBURST(PU_SPS2_AWBURST),
    .PU_SPS2_AWLOCK(PU_SPS2_AWLOCK),
    .PU_SPS2_AWCACHE(PU_SPS2_AWCACHE),
    .PU_SPS2_AWPROT(PU_SPS2_AWPROT),
    .PU_SPS2_AWQOS(PU_SPS2_AWQOS),
    .PU_SPS2_AWREADY(PU_SPS2_AWREADY),
    .PU_SPS2_WVALID(PU_SPS2_WVALID),
    .PU_SPS2_WDATA(pu_sps2_wdata),
    .PU_SPS2_WSTRB(pu_sps2_wstrb),
    .PU_SPS2_WLAST(PU_SPS2_WLAST),
    .PU_SPS2_WREADY(PU_SPS2_WREADY),
    .PU_SPS2_BVALID(PU_SPS2_BVALID),
    .PU_SPS2_BID(PU_SPS2_BID_out),
    .PU_SPS2_BRESP(PU_SPS2_BRESP),
    .PU_SPS2_BREADY(PU_SPS2_BREADY),
    .PU_SPS2_ARVALID(PU_SPS2_ARVALID),
    .PU_SPS2_ARID(PU_SPS2_ARID_in),
    .PU_SPS2_ARADDR(PU_SPS2_ARADDR),
    .PU_SPS2_ARLEN(PU_SPS2_ARLEN),
    .PU_SPS2_ARSIZE(PU_SPS2_ARSIZE),
    .PU_SPS2_ARBURST(PU_SPS2_ARBURST),
    .PU_SPS2_ARLOCK(PU_SPS2_ARLOCK),
    .PU_SPS2_ARCACHE(PU_SPS2_ARCACHE),
    .PU_SPS2_ARPROT(PU_SPS2_ARPROT),
    .PU_SPS2_ARQOS(PU_SPS2_ARQOS),
    .PU_SPS2_ARREADY(PU_SPS2_ARREADY),
    .PU_SPS2_RVALID(PU_SPS2_RVALID),
    .PU_SPS2_RID(PU_SPS2_RID_out),
    .PU_SPS2_RDATA(pu_sps2_rdata),
    .PU_SPS2_RRESP(PU_SPS2_RRESP),
    .PU_SPS2_RLAST(PU_SPS2_RLAST),
    .PU_SPS2_RREADY(PU_SPS2_RREADY),

    .PU_SPS3_CLK(S_AXI_SPS3_ACLK_temp),
    .PU_SPS3_RESETN(PU_SPS3_RESETN),
    .PU_SPS3_AWVALID(PU_SPS3_AWVALID),
    .PU_SPS3_AWADDR(PU_SPS3_AWADDR),
    .PU_SPS3_AWID(PU_SPS3_AWID_in),
    .PU_SPS3_AWLEN(PU_SPS3_AWLEN),
    .PU_SPS3_AWSIZE(PU_SPS3_AWSIZE),
    .PU_SPS3_AWBURST(PU_SPS3_AWBURST),
    .PU_SPS3_AWLOCK(PU_SPS3_AWLOCK),
    .PU_SPS3_AWCACHE(PU_SPS3_AWCACHE),
    .PU_SPS3_AWPROT(PU_SPS3_AWPROT),
    .PU_SPS3_AWQOS(PU_SPS3_AWQOS),
    .PU_SPS3_AWREADY(PU_SPS3_AWREADY),
    .PU_SPS3_WVALID(PU_SPS3_WVALID),
    .PU_SPS3_WDATA(pu_sps3_wdata),
    .PU_SPS3_WSTRB(pu_sps3_wstrb),
    .PU_SPS3_WLAST(PU_SPS3_WLAST),
    .PU_SPS3_WREADY(PU_SPS3_WREADY),
    .PU_SPS3_BVALID(PU_SPS3_BVALID),
    .PU_SPS3_BID(PU_SPS3_BID_out),
    .PU_SPS3_BRESP(PU_SPS3_BRESP),
    .PU_SPS3_BREADY(PU_SPS3_BREADY),
    .PU_SPS3_ARVALID(PU_SPS3_ARVALID),
    .PU_SPS3_ARID(PU_SPS3_ARID_in),
    .PU_SPS3_ARADDR(PU_SPS3_ARADDR),
    .PU_SPS3_ARLEN(PU_SPS3_ARLEN),
    .PU_SPS3_ARSIZE(PU_SPS3_ARSIZE),
    .PU_SPS3_ARBURST(PU_SPS3_ARBURST),
    .PU_SPS3_ARLOCK(PU_SPS3_ARLOCK),
    .PU_SPS3_ARCACHE(PU_SPS3_ARCACHE),
    .PU_SPS3_ARPROT(PU_SPS3_ARPROT),
    .PU_SPS3_ARQOS(PU_SPS3_ARQOS),
    .PU_SPS3_ARREADY(PU_SPS3_ARREADY),
    .PU_SPS3_RVALID(PU_SPS3_RVALID),
    .PU_SPS3_RID(PU_SPS3_RID_out),
    .PU_SPS3_RDATA(pu_sps3_rdata),
    .PU_SPS3_RRESP(PU_SPS3_RRESP),
    .PU_SPS3_RLAST(PU_SPS3_RLAST),
    .PU_SPS3_RREADY(PU_SPS3_RREADY),

    .PU_AWURGENT0(PU_AWURGENT0),
    .PU_AWURGENT1(PU_AWURGENT1),
    .PU_AWURGENT2(PU_AWURGENT2),
    .PU_AWURGENT3(PU_AWURGENT3),
    .PU_ARURGENT0(PU_ARURGENT0),
    .PU_ARURGENT1(PU_ARURGENT1),
    .PU_ARURGENT2(PU_ARURGENT2),
    .PU_ARURGENT3(PU_ARURGENT3),

    .PU_DMA_CLK0(PU_DMA0_CLK),
    .PU_DMA_LAST0(PU_DMA0_LAST),
    .PU_DMA_REQ0(PU_DMA0_REQ),
    .PU_DMA_RESETN0(PU_DMA0_RESETN),
    .PU_DMA_SINGLE0(PU_DMA0_SINGLE),
    .PU_DMA_ACK0(PU_DMA0_ACK),
    .PU_DMA_FINISH0(PU_DMA0_FINISH),

    .PU_DMA_CLK1(PU_DMA1_CLK),
    .PU_DMA_LAST1(PU_DMA1_LAST),
    .PU_DMA_REQ1(PU_DMA1_REQ),
    .PU_DMA_RESETN1(PU_DMA1_RESETN),
    .PU_DMA_SINGLE1(PU_DMA1_SINGLE),
    .PU_DMA_ACK1(PU_DMA1_ACK),
    .PU_DMA_FINISH1(PU_DMA1_FINISH),

    .PU_DMA_CLK2(PU_DMA2_CLK),
    .PU_DMA_LAST2(PU_DMA2_LAST),
    .PU_DMA_REQ2(PU_DMA2_REQ),
    .PU_DMA_RESETN2(PU_DMA2_RESETN),
    .PU_DMA_SINGLE2(PU_DMA2_SINGLE),
    .PU_DMA_ACK2(PU_DMA2_ACK),
    .PU_DMA_FINISH2(PU_DMA2_FINISH),

    .PU_DMA_CLK3(PU_DMA3_CLK),
    .PU_DMA_LAST3(PU_DMA3_LAST),
    .PU_DMA_REQ3(PU_DMA3_REQ),
    .PU_DMA_RESETN3(PU_DMA3_RESETN),
    .PU_DMA_SINGLE3(PU_DMA3_SINGLE),
    .PU_DMA_ACK3(PU_DMA3_ACK),
    .PU_DMA_FINISH3(PU_DMA3_FINISH),

    .PU_IOMUX_CAN0_TXD(PU_IOMUX_CAN0_TXD),
    .PU_IOMUX_CAN0_RXD(PU_IOMUX_CAN0_RXD),

    .PU_IOMUX_CAN1_TXD(PU_IOMUX_CAN1_TXD),
    .PU_IOMUX_CAN1_RXD(PU_IOMUX_CAN1_RXD),

    .PU_IOMUX_ENET0_MD_I(PU_IOMUX_ENET0_MD_I),
    .PU_IOMUX_ENET0_MD_O(PU_IOMUX_ENET0_MD_O),
    .PU_IOMUX_ENET0_MD_TN(PU_IOMUX_ENET0_MD_TN),
    .PU_IOMUX_ENET0_MDC(PU_IOMUX_ENET0_MDC),
    .PU_IOMUX_ENET0_TXD(PU_IOMUX_ENET0_TXD),
    .PU_IOMUX_ENET0_TXEN(PU_IOMUX_ENET0_TXEN),
    .PU_IOMUX_ENET0_TXER(PU_IOMUX_ENET0_TXER),
    .PU_IOMUX_ENET0_COL(PU_IOMUX_ENET0_COL),
    .PU_IOMUX_ENET0_CRS(PU_IOMUX_ENET0_CRS),
    .PU_IOMUX_ENET0_MIITXC(PU_IOMUX_ENET0_MIITXC),
    .PU_IOMUX_ENET0_GMIIRXC(PU_IOMUX_ENET0_GMIIRXC),
    .PU_IOMUX_ENET0_GMIITXC(PU_IOMUX_ENET0_GMIITXC),
    .PU_IOMUX_ENET0_IRQF2P(PU_IOMUX_ENET0_IRQF2P),
    .PU_IOMUX_ENET0_RXD(PU_IOMUX_ENET0_RXD),
    .PU_IOMUX_ENET0_RXDV(PU_IOMUX_ENET0_RXDV),
    .PU_IOMUX_ENET0_RXER(PU_IOMUX_ENET0_RXER),
    .PU_IOMUX_ENET0_AUX_TS_TRIG(PU_IOMUX_ENET0_AUX_TS_TRIG),
    .PU_IOMUX_ENET0_MCG_PST_TRIG(PU_IOMUX_ENET0_MCG_PST_TRIG),
    .PU_IOMUX_ENET0_MCGR_DMA_ACK(PU_IOMUX_ENET0_MCGR_DMA_ACK),
    .PU_IOMUX_ENET0_MCGR_DMA_REQ(PU_IOMUX_ENET0_MCGR_DMA_REQ),
    .PU_IOMUX_ENET0_PPS(PU_IOMUX_ENET0_PPS),
    .PU_IOMUX_ENET0_TIMESTAMP(PU_IOMUX_ENET0_TIMESTAMP),

    .PU_IOMUX_ENET1_MD_I(PU_IOMUX_ENET1_MD_I),
    .PU_IOMUX_ENET1_MD_O(PU_IOMUX_ENET1_MD_O),
    .PU_IOMUX_ENET1_MD_TN(PU_IOMUX_ENET1_MD_TN),
    .PU_IOMUX_ENET1_MDC(PU_IOMUX_ENET1_MDC),
    .PU_IOMUX_ENET1_TXD(PU_IOMUX_ENET1_TXD),
    .PU_IOMUX_ENET1_TXEN(PU_IOMUX_ENET1_TXEN),
    .PU_IOMUX_ENET1_TXER(PU_IOMUX_ENET1_TXER),
    .PU_IOMUX_ENET1_COL(PU_IOMUX_ENET1_COL),
    .PU_IOMUX_ENET1_CRS(PU_IOMUX_ENET1_CRS),
    .PU_IOMUX_ENET1_MIITXC(PU_IOMUX_ENET1_MIITXC),
    .PU_IOMUX_ENET1_GMIIRXC(PU_IOMUX_ENET1_GMIIRXC),
    .PU_IOMUX_ENET1_GMIITXC(PU_IOMUX_ENET1_GMIITXC),
    .PU_IOMUX_ENET1_IRQF2P(PU_IOMUX_ENET1_IRQF2P),
    .PU_IOMUX_ENET1_RXD(PU_IOMUX_ENET1_RXD),
    .PU_IOMUX_ENET1_RXDV(PU_IOMUX_ENET1_RXDV),
    .PU_IOMUX_ENET1_RXER(PU_IOMUX_ENET1_RXER),
    .PU_IOMUX_ENET1_AUX_TS_TRIG(PU_IOMUX_ENET1_AUX_TS_TRIG),
    .PU_IOMUX_ENET1_MCFG_DMA_ACK(PU_IOMUX_ENET1_MCFG_DMA_ACK),
    .PU_IOMUX_ENET1_MCG_PST_TRIG(PU_IOMUX_ENET1_MCG_PST_TRIG),
    .PU_IOMUX_ENET1_MCFGR_DMA_REQ(PU_IOMUX_ENET1_MCFGR_DMA_REQ),
    .PU_IOMUX_ENET1_PPS(PU_IOMUX_ENET1_PPS),
    .PU_IOMUX_ENET1_TIMESTAMP(PU_IOMUX_ENET1_TIMESTAMP),

    .PU_IOMUX_GPIO_C_O(ntPU_IOMUX_GPIO_O[31:0]),
    .PU_IOMUX_GPIO_D_O(ntPU_IOMUX_GPIO_O[63:32]),
    .PU_IOMUX_GPIO_C_TN(ntPU_IOMUX_GPIO_TN[31:0]),
    .PU_IOMUX_GPIO_D_TN(ntPU_IOMUX_GPIO_TN[63:32]),
    .PU_IOMUX_GPIO_C_I(ntPU_IOMUX_GPIO_I[31:0]),
    .PU_IOMUX_GPIO_D_I(ntPU_IOMUX_GPIO_I[63:32]),

    .PU_IOMUX_I2C0_SCL_O(PU_IOMUX_I2C0_SCL_O),
    .PU_IOMUX_I2C0_SCL_TN(PU_IOMUX_I2C0_SCL_TN),
    .PU_IOMUX_I2C0_SCL_I(PU_IOMUX_I2C0_SCL_I),
    .PU_IOMUX_I2C0_SDA_O(PU_IOMUX_I2C0_SDA_O),
    .PU_IOMUX_I2C0_SDA_TN(PU_IOMUX_I2C0_SDA_TN),
    .PU_IOMUX_I2C0_SDA_I(PU_IOMUX_I2C0_SDA_I),

    .PU_IOMUX_I2C1_SCL_O(PU_IOMUX_I2C1_SCL_O),
    .PU_IOMUX_I2C1_SCL_TN(PU_IOMUX_I2C1_SCL_TN),
    .PU_IOMUX_I2C1_SCL_I(PU_IOMUX_I2C1_SCL_I),
    .PU_IOMUX_I2C1_SDA_O(PU_IOMUX_I2C1_SDA_O),
    .PU_IOMUX_I2C1_SDA_TN(PU_IOMUX_I2C1_SDA_TN),
    .PU_IOMUX_I2C1_SDA_I(PU_IOMUX_I2C1_SDA_I),

    .PU_IOMUX_PAJTAG_TDO(PU_IOMUX_PAJTAG_TDO),
    .PU_IOMUX_PAJTAG_TDO_TN(PU_IOMUX_PAJTAG_TDO_TN),
    .PU_IOMUX_PAJTAG_TCK(PU_IOMUX_PAJTAG_TCK),
    .PU_IOMUX_PAJTAG_TDI(PU_IOMUX_PAJTAG_TDI),
    .PU_IOMUX_PAJTAG_TMS(PU_IOMUX_PAJTAG_TMS),

    .PU_IOMUX_SDIO0_BUS_POW(PU_IOMUX_SDIO0_BUS_POW),
    .PU_IOMUX_SDIO0_BUS_VOLT(PU_IOMUX_SDIO0_BUS_VOLT),
    .PU_IOMUX_SDIO0_CLK_O(PU_IOMUX_SDIO0_CLK_O),
    .PU_IOMUX_SDIO0_CMD_I(PU_IOMUX_SDIO0_CMD_I),
    .PU_IOMUX_SDIO0_CMD_O(PU_IOMUX_SDIO0_CMD_O),
    .PU_IOMUX_SDIO0_CMD_TN(PU_IOMUX_SDIO0_CMD_TN),
    .PU_IOMUX_SDIO0_DATA_I(PU_IOMUX_SDIO0_DATA_I),
    .PU_IOMUX_SDIO0_DATA_O(PU_IOMUX_SDIO0_DATA_O),
    .PU_IOMUX_SDIO0_DATA_TN(PU_IOMUX_SDIO0_DATA_TN),
    .PU_IOMUX_SDIO0_LED(PU_IOMUX_SDIO0_LED),
    .PU_IOMUX_SDIO0_CDN(PU_IOMUX_SDIO0_CDN),
    .PU_IOMUX_SDIO0_CLK_I(PU_IOMUX_SDIO0_CLK_I),
    .PU_IOMUX_SDIO0_WP(PU_IOMUX_SDIO0_WP),
    .PU_IOMUX_SDIO0_RST_N(PU_IOMUX_SDIO0_RST_N),
    .PU_IOMUX_SDIO0_RST_N_TN(PU_IOMUX_SDIO0_RST_N_TN),

    .PU_IOMUX_SDIO1_BUS_POW(PU_IOMUX_SDIO1_BUS_POW),
    .PU_IOMUX_SDIO1_BUS_VOLT(PU_IOMUX_SDIO1_BUS_VOLT),
    .PU_IOMUX_SDIO1_CLK_O(PU_IOMUX_SDIO1_CLK_O),
    .PU_IOMUX_SDIO1_CMD_I(PU_IOMUX_SDIO1_CMD_I),
    .PU_IOMUX_SDIO1_CMD_O(PU_IOMUX_SDIO1_CMD_O),
    .PU_IOMUX_SDIO1_CMD_TN(PU_IOMUX_SDIO1_CMD_TN),
    .PU_IOMUX_SDIO1_DATA_I(PU_IOMUX_SDIO1_DATA_I),
    .PU_IOMUX_SDIO1_DATA_O(PU_IOMUX_SDIO1_DATA_O),
    .PU_IOMUX_SDIO1_DATA_TN(PU_IOMUX_SDIO1_DATA_TN),
    .PU_IOMUX_SDIO1_LED(PU_IOMUX_SDIO1_LED),
    .PU_IOMUX_SDIO1_CDN(PU_IOMUX_SDIO1_CDN),
    .PU_IOMUX_SDIO1_CLK_I(PU_IOMUX_SDIO1_CLK_I),
    .PU_IOMUX_SDIO1_WP(PU_IOMUX_SDIO1_WP),
    .PU_IOMUX_SDIO1_RST_N(PU_IOMUX_SDIO1_RST_N),
    .PU_IOMUX_SDIO1_RST_N_TN(PU_IOMUX_SDIO1_RST_N_TN),

    .PU_IOMUX_SPI0_MISO_O(PU_IOMUX_SPI0_MISO_O),
    .PU_IOMUX_SPI0_MOSI_O(PU_IOMUX_SPI0_MOSI_O),
    .PU_IOMUX_SPI0_SCLK_O(PU_IOMUX_SPI0_SCLK_O),
    .PU_IOMUX_SPI0_SSN_O({PU_IOMUX_SPI0_SSN_O_2,PU_IOMUX_SPI0_SSN_O_1,PU_IOMUX_SPI0_SSN_O_0}),
    .PU_IOMUX_SPI0_MISO_I(PU_IOMUX_SPI0_MISO_I),
    .PU_IOMUX_SPI0_MOSI_I(PU_IOMUX_SPI0_MOSI_I),
    .PU_IOMUX_SPI0_SCLK_I(PU_IOMUX_SPI0_SCLK_I),
    .PU_IOMUX_SPI0_SSN_I(PU_IOMUX_SPI0_SSN_I),
    .PU_IOMUX_SPI0_MST_SSI_OE_N(PU_IOMUX_SPI0_MST_SSI_OE_N),
    .PU_IOMUX_SPI0_SLV_SSI_OE_N(PU_IOMUX_SPI0_SLV_SSI_OE_N),

    .PU_IOMUX_SPI1_MISO_O(PU_IOMUX_SPI1_MISO_O),
    .PU_IOMUX_SPI1_MOSI_O(PU_IOMUX_SPI1_MOSI_O),
    .PU_IOMUX_SPI1_SCLK_O(PU_IOMUX_SPI1_SCLK_O),
    .PU_IOMUX_SPI1_SSN_O({PU_IOMUX_SPI1_SSN_O_2,PU_IOMUX_SPI1_SSN_O_1,PU_IOMUX_SPI1_SSN_O_0}),
    .PU_IOMUX_SPI1_MISO_I(PU_IOMUX_SPI1_MISO_I),
    .PU_IOMUX_SPI1_MOSI_I(PU_IOMUX_SPI1_MOSI_I),
    .PU_IOMUX_SPI1_SCLK_I(PU_IOMUX_SPI1_SCLK_I),
    .PU_IOMUX_SPI1_SSN_I(PU_IOMUX_SPI1_SSN_I),
    .PU_IOMUX_SPI1_MST_SSI_OE_N(PU_IOMUX_SPI1_MST_SSI_OE_N),
    .PU_IOMUX_SPI1_SLV_SSI_OE_N(PU_IOMUX_SPI1_SLV_SSI_OE_N),

    .PU_IOMUX_TRACE_CTL(TRACE_CTL),
    .PU_IOMUX_TRACE_DATA(TRACE_DATA),
    .PU_IOMUX_TRACE_CLKI(PU_IOMUX_TRACE_CLKI),

    .PU_IOMUX_TTC0_WAVEO(PU_IOMUX_TTC0_WAVEO),
    .PU_IOMUX_TTC0_PAUSE(PU_IOMUX_TTC0_PAUSE),
	
    .PU_IOMUX_TTC1_WAVEO(PU_IOMUX_TTC1_WAVEO),
    .PU_IOMUX_TTC1_PAUSE(PU_IOMUX_TTC1_PAUSE),

    .PU_IOMUX_UART0_DTR_N(PU_IOMUX_UART0_DTR_N),
    .PU_IOMUX_UART0_RTS_N(PU_IOMUX_UART0_RTS_N),
    .PU_IOMUX_UART0_TXD(PU_IOMUX_UART0_TXD),
    .PU_IOMUX_UART0_CTS_N(PU_IOMUX_UART0_CTS_N),
    .PU_IOMUX_UART0_DCD_N(PU_IOMUX_UART0_DCD_N),
    .PU_IOMUX_UART0_DSR_N(PU_IOMUX_UART0_DSR_N),
    .PU_IOMUX_UART0_RI_N(PU_IOMUX_UART0_RI_N),
    .PU_IOMUX_UART0_RXD(PU_IOMUX_UART0_RXD),

    .PU_IOMUX_UART1_DTR_N(PU_IOMUX_UART1_DTR_N),
    .PU_IOMUX_UART1_RTS_N(PU_IOMUX_UART1_RTS_N),
    .PU_IOMUX_UART1_TXD(PU_IOMUX_UART1_TXD),
    .PU_IOMUX_UART1_CTS_N(PU_IOMUX_UART1_CTS_N),
    .PU_IOMUX_UART1_DCD_N(PU_IOMUX_UART1_DCD_N),
    .PU_IOMUX_UART1_DSR_N(PU_IOMUX_UART1_DSR_N),
    .PU_IOMUX_UART1_RI_N(PU_IOMUX_UART1_RI_N),
    .PU_IOMUX_UART1_RXD(PU_IOMUX_UART1_RXD),

    .PU_IOMUX_WDT_RSTO(PU_IOMUX_WDT_RSTO),
    .PU_IOMUX_WDT_PAUSE(PU_IOMUX_WDT_PAUSE),

    .PU_IOMUX_PA_IDLE_N(PU_IOMUX_PA_IDLE_N),

    .PU_IOMUX_EVENT_I(PU_IOMUX_EVENT_I),
    .PU_IOMUX_EVENT_O(PU_IOMUX_EVENT_O),
	
    .PU_IOMUX_IRQPA2PU(pu_irqpa2pu),
    .PU_IOMUX_IRQPU2PA(pu_irqpu2pa),
	
    .PU_IOMUX_STANDBY_WFE(PU_IOMUX_STANDBY_WFE),
    .PU_IOMUX_STANDBY_WFI(PU_IOMUX_STANDBY_WFI),

    .PU_IOMUX_PATMDTRACEINATID(FTMD_TRACEIN_ATID),
    .PU_IOMUX_PATMDTRACEINCLOCK(PU_IOMUX_PATMDTRACEINCLOCK),
    .PU_IOMUX_PATMDTRACEINDATA(FTMD_TRACEIN_DATA),
    .PU_IOMUX_PATMDTRACEINVALID(FTMD_TRACEIN_VALID),

    .PU_IOMUX_PATMTPA2PUDDEBUG(PU_IOMUX_PATMTPA2PUDDEBUG),
    .PU_IOMUX_PATMTPU2PADDEBUG(PU_IOMUX_PATMTPU2PADDEBUG),

    .PU_IOMUX_PATMTPA2PUTRIG(PU_IOMUX_PATMTPA2PUTRIG),
    .PU_IOMUX_PATMTPU2PATRIG(PU_IOMUX_PATMTPU2PATRIG),
    .PU_IOMUX_PATMTPA2PUTRIGACK(PU_IOMUX_PATMTPA2PUTRIGACK),
    .PU_IOMUX_PATMTPU2PATRIGACK(PU_IOMUX_PATMTPU2PATRIGACK),
	
    .PU_IOMUX_ENET_PTP_REF(PU_IOMUX_ENET_PTP_REF),

    .PU_PACLK0_CLK_TRIG_N(PU_PACLK0_CLK_TRIG_N),
    .PU_PACLK1_CLK_TRIG_N(PU_PACLK1_CLK_TRIG_N),
    .PU_PACLK2_CLK_TRIG_N(PU_PACLK2_CLK_TRIG_N),
    .PU_PACLK3_CLK_TRIG_N(PU_PACLK3_CLK_TRIG_N),

    .PU_IOMUX_PACLK0_RESETN(PU_IOMUX_PACLK0_RESETN),
    .PU_IOMUX_PACLK1_RESETN(PU_IOMUX_PACLK1_RESETN),
    .PU_IOMUX_PACLK2_RESETN(PU_IOMUX_PACLK2_RESETN),
    .PU_IOMUX_PACLK3_RESETN(PU_IOMUX_PACLK3_RESETN),

    .PU_IOMUX_PACLK(FCLK_CLK_unbuffered)
);
endmodule
