import { choropleth, formatNumber, landfallIndex } from "./color";

describe("choropleth", () => {
  it("keeps empty counties dark and uses a lighter color for larger values", () => {
    expect(choropleth(0, 100)).toBe("#1c3142");
    expect(choropleth(100, 100)).not.toBe(choropleth(1, 100));
    expect(choropleth(25, 100)).not.toBe(choropleth(0, 100));
  });
});

describe("landfall frame", () => {
  it("picks the strongest wind fix over Florida", () => {
    const index = landfallIndex([
      { position: [-70, 20], wind_kt: 140 },
      { position: [-82.2, 26.7], wind_kt: 130 },
      { position: [-81.7, 27.2], wind_kt: 100 },
    ]);
    expect(index).toBe(1);
  });
});

describe("formatNumber", () => {
  it("groups digits", () => {
    expect(formatNumber(1447)).toBe("1,447");
  });
});
