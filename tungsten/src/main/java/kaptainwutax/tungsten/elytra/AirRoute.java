package kaptainwutax.tungsten.elytra;

import net.minecraft.util.math.BlockPos;
import net.minecraft.util.math.MathHelper;
import net.minecraft.util.math.Vec3d;
import net.minecraft.world.BlockView;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.PriorityQueue;

/**
 * The way through the air to a point, on a coarse grid: cells of {@link #CELL} blocks, a cell open when
 * no block in it has collision, A* over the 26 neighbours. Climbing costs more than descending (height
 * is bought with rockets, a glide gives it back as distance), a cell next to a closed one costs extra
 * (a glider needs room). The cell path is then pulled straight: only the corners a straight flight
 * cannot cut remain, and the solver flies them like rings.
 *
 * <p>The search reads the world off the client thread; a chunk not loaded counts as open but dear.
 * Meant to run on a worker while the glider circles.
 */
public final class AirRoute {

    public static final int CELL = 4;
    private static final int MAX_NODES = 40_000;

    private record Node(int x, int y, int z, double g, double f, Node parent) {
    }

    private AirRoute() {
    }

    /** Corners from start to goal (goal included, start not), or null when no way was found. */
    public static List<Vec3d> find(BlockView world, Vec3d start, Vec3d goal, int minY, int maxY) {
        int sx = cell(start.x), sy = cell(start.y), sz = cell(start.z);
        int gx = cell(goal.x), gy = cell(goal.y), gz = cell(goal.z);
        int cyMin = cell(minY), cyMax = cell(maxY);
        Map<Long, Double> best = new HashMap<>();
        Map<Long, Boolean> openCache = new HashMap<>();
        PriorityQueue<Node> q = new PriorityQueue<>((a, b) -> Double.compare(a.f(), b.f()));
        q.add(new Node(sx, sy, sz, 0, h(sx, sy, sz, gx, gy, gz), null));
        best.put(key(sx, sy, sz), 0.0);
        Node found = null, closest = null;
        double closestH = Double.MAX_VALUE;
        int expanded = 0;
        while (!q.isEmpty() && expanded < MAX_NODES) {
            Node n = q.poll();
            if (n.g() > best.getOrDefault(key(n.x(), n.y(), n.z()), Double.MAX_VALUE)) continue;
            expanded++;
            double hn = h(n.x(), n.y(), n.z(), gx, gy, gz);
            if (hn < closestH) {
                closestH = hn;
                closest = n;
            }
            if (n.x() == gx && n.y() == gy && n.z() == gz) {
                found = n;
                break;
            }
            for (int dx = -1; dx <= 1; dx++) {
                for (int dy = -1; dy <= 1; dy++) {
                    for (int dz = -1; dz <= 1; dz++) {
                        if (dx == 0 && dy == 0 && dz == 0) continue;
                        int x = n.x() + dx, y = n.y() + dy, z = n.z() + dz;
                        if (y < cyMin || y > cyMax) continue;
                        boolean goalCell = x == gx && y == gy && z == gz;
                        if (!goalCell && !open(world, x, y, z, openCache)) continue;
                        // diagonal moves must not cut a closed cell's corner
                        if ((dx != 0 && dy != 0 || dx != 0 && dz != 0 || dy != 0 && dz != 0)
                                && (!open(world, n.x() + dx, n.y(), n.z(), openCache) && dx != 0
                                || !open(world, n.x(), n.y() + dy, n.z(), openCache) && dy != 0
                                || !open(world, n.x(), n.y(), n.z() + dz, openCache) && dz != 0)) continue;
                        double step = Math.sqrt(dx * dx + dy * dy + dz * dz);
                        double cost = step + (dy > 0 ? 2.0 : dy < 0 ? -0.3 : 0) + crowd(world, x, y, z, openCache);
                        double g = n.g() + cost;
                        long k = key(x, y, z);
                        if (g < best.getOrDefault(k, Double.MAX_VALUE)) {
                            best.put(k, g);
                            q.add(new Node(x, y, z, g, g + h(x, y, z, gx, gy, gz), n));
                        }
                    }
                }
            }
        }
        if (found == null) return null;
        List<Vec3d> cells = new ArrayList<>();
        for (Node n = found; n != null; n = n.parent()) cells.add(0, centre(n.x(), n.y(), n.z()));
        cells.set(cells.size() - 1, goal);
        return pull(world, start, cells);
    }

    /** Longest straight leg kept: the solver sees two seconds ahead, so between corners further apart
     *  it threads the gaps on its own -- once it did, once it climbed into the corner over a gap
     *  (01.11, the maze). A point every 28 blocks keeps it on the searched way. */
    private static final double MAX_LEG = 28;

    /** String pulling: from each kept point, the furthest point still in clear sight with room, at
     *  most {@link #MAX_LEG} away. */
    private static List<Vec3d> pull(BlockView world, Vec3d start, List<Vec3d> pts) {
        List<Vec3d> out = new ArrayList<>();
        Vec3d from = start;
        int i = 0;
        while (i < pts.size()) {
            int far = i;
            for (int j = pts.size() - 1; j > i; j--) {
                if (pts.get(j).distanceTo(from) <= MAX_LEG && clear(world, from, pts.get(j))) {
                    far = j;
                    break;
                }
            }
            out.add(pts.get(far));
            from = pts.get(far);
            i = far + 1;
        }
        return out;
    }

    /** A straight flight from a to b keeps a block and a half from any block (sampled every block). */
    public static boolean clear(BlockView world, Vec3d a, Vec3d b) {
        Vec3d d = b.subtract(a);
        int n = Math.max(1, (int) Math.ceil(d.length()));
        for (int i = 0; i <= n; i++) {
            Vec3d p = a.add(d.multiply(i / (double) n));
            for (double ox = -1.5; ox <= 1.5; ox += 1.5) {
                for (double oy = -1.0; oy <= 1.5; oy += 1.25) {
                    for (double oz = -1.5; oz <= 1.5; oz += 1.5) {
                        if (solid(world, MathHelper.floor(p.x + ox), MathHelper.floor(p.y + oy), MathHelper.floor(p.z + oz))) {
                            return false;
                        }
                    }
                }
            }
        }
        return true;
    }

    private static boolean open(BlockView world, int cx, int cy, int cz, Map<Long, Boolean> cache) {
        return cache.computeIfAbsent(key(cx, cy, cz), k -> {
            int x0 = cx * CELL, y0 = cy * CELL, z0 = cz * CELL;
            for (int x = x0; x < x0 + CELL; x++) {
                for (int y = y0; y < y0 + CELL; y++) {
                    for (int z = z0; z < z0 + CELL; z++) {
                        if (solid(world, x, y, z)) return false;
                    }
                }
            }
            return true;
        });
    }

    /** Extra cost for a cell with closed cells around it: a glider wants room. */
    private static double crowd(BlockView world, int x, int y, int z, Map<Long, Boolean> cache) {
        int closed = 0;
        if (!open(world, x + 1, y, z, cache)) closed++;
        if (!open(world, x - 1, y, z, cache)) closed++;
        if (!open(world, x, y + 1, z, cache)) closed++;
        if (!open(world, x, y - 1, z, cache)) closed++;
        if (!open(world, x, y, z + 1, cache)) closed++;
        if (!open(world, x, y, z - 1, cache)) closed++;
        return closed * 0.8;
    }

    private static boolean solid(BlockView world, int x, int y, int z) {
        try {
            BlockPos p = new BlockPos(x, y, z);
            var st = world.getBlockState(p);
            return st != null && !st.getCollisionShape(world, p).isEmpty();
        } catch (Exception e) { // a chunk unloading under the worker: count it open
            return false;
        }
    }

    private static int cell(double v) {
        return MathHelper.floor(v / CELL);
    }

    private static Vec3d centre(int x, int y, int z) {
        return new Vec3d(x * CELL + CELL / 2.0, y * CELL + CELL / 2.0, z * CELL + CELL / 2.0);
    }

    private static double h(int x, int y, int z, int gx, int gy, int gz) {
        return Math.sqrt((double) (x - gx) * (x - gx) + (double) (y - gy) * (y - gy) + (double) (z - gz) * (z - gz));
    }

    private static long key(int x, int y, int z) {
        return ((long) (x & 0x3FFFFF) << 42) | ((long) (y & 0xFFFFF) << 22) | (z & 0x3FFFFF);
    }
}
